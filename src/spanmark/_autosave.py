"""Private append-only autosave overlay for annotation state."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from spanmark._storage import FileFingerprint, _fsync_directory

AUTOSAVE_CHECKPOINT_BYTES = 16 * 1024 * 1024
_AUTOSAVE_VERSION = 1


@dataclass(frozen=True, slots=True)
class AutosaveRecovery:
    """Latest complete annotation states recovered from an autosave overlay."""

    base: FileFingerprint
    annotations: Mapping[str, Mapping[str, Any]]


class AutosaveOverlay:
    """An append-only overlay of per-document states beside a JSONL checkpoint."""

    def __init__(self, output_path: Path) -> None:
        self.path = output_path.with_name(f".{output_path.name}.spanmark-autosave")

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def append(
        self,
        *,
        base: FileFingerprint,
        document_id: str,
        annotation: Mapping[str, Any],
    ) -> None:
        """Durably append the latest complete annotation state for one document."""
        if self.exists:
            if self._read_header() != base:
                raise RuntimeError(
                    f"Autosave overlay {self.path} does not match the current "
                    "JSONL checkpoint"
                )
        else:
            self._write_header(base)

        self._append_line(
            {
                "type": "state",
                "id": document_id,
                "annotation": dict(annotation),
            }
        )

    def recover(self) -> AutosaveRecovery | None:
        """Read complete overlay records, ignoring only a torn final line."""
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return None

        lines = data.splitlines(keepends=True)
        complete_lines: list[bytes] = []
        for index, line in enumerate(lines):
            if line.endswith(b"\n"):
                complete_lines.append(line)
                continue
            if index == len(lines) - 1:
                break
            raise ValueError(f"Autosave overlay {self.path} contains a malformed line")

        if not complete_lines:
            return None

        header = _decode_object(complete_lines[0], path=self.path, line_number=1)
        base = _parse_header(header, path=self.path)
        annotations: dict[str, Mapping[str, Any]] = {}

        for line_number, raw_line in enumerate(complete_lines[1:], start=2):
            raw = _decode_object(
                raw_line,
                path=self.path,
                line_number=line_number,
            )
            if raw.get("type") != "state":
                raise ValueError(
                    f"Invalid autosave record in {self.path} line {line_number}: "
                    "expected type 'state'"
                )

            document_id = raw.get("id")
            if not isinstance(document_id, str) or not document_id:
                raise ValueError(
                    f"Invalid autosave record in {self.path} line {line_number}: "
                    "id must be a non-empty string"
                )

            annotation = raw.get("annotation")
            if not isinstance(annotation, Mapping):
                raise ValueError(
                    f"Invalid autosave record in {self.path} line {line_number}: "
                    "annotation must be an object"
                )
            annotations[document_id] = cast(Mapping[str, Any], annotation)

        return AutosaveRecovery(base=base, annotations=annotations)

    def discard(self) -> None:
        """Remove the overlay after its state is present in the JSONL checkpoint."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(self.path.parent)

    def _write_header(self, base: FileFingerprint) -> None:
        header = _encode_line(
            {
                "type": "header",
                "version": _AUTOSAVE_VERSION,
                "base": {"size": base.size, "sha256": base.sha256},
            }
        )
        created = False

        try:
            with self.path.open("xb") as file:
                created = True
                file.write(header)
                file.flush()
                os.fsync(file.fileno())
            _fsync_directory(self.path.parent)
        except BaseException:
            if created:
                try:
                    self.path.unlink(missing_ok=True)
                    _fsync_directory(self.path.parent)
                except OSError:
                    pass
            raise

    def _read_header(self) -> FileFingerprint:
        with self.path.open("rb") as file:
            raw_line = file.readline()

        if not raw_line.endswith(b"\n"):
            raise ValueError(f"Autosave overlay {self.path} has an incomplete header")

        raw = _decode_object(raw_line, path=self.path, line_number=1)
        return _parse_header(raw, path=self.path)

    def _append_line(self, record: Mapping[str, Any]) -> None:
        line = _encode_line(record)
        previous_size = self.path.stat().st_size

        try:
            with self.path.open("ab") as file:
                file.write(line)
                file.flush()
                os.fsync(file.fileno())
        except BaseException:
            try:
                with self.path.open("r+b") as file:
                    file.truncate(previous_size)
                    file.flush()
                    os.fsync(file.fileno())
            except OSError:
                pass
            raise


def _encode_line(record: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _decode_object(
    raw_line: bytes,
    *,
    path: Path,
    line_number: int,
) -> Mapping[str, Any]:
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Invalid UTF-8 in autosave overlay {path} line {line_number}"
        ) from exc

    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in autosave overlay {path} line {line_number}"
        ) from exc

    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Autosave overlay {path} line {line_number} must contain an object"
        )
    return cast(Mapping[str, Any], raw)


def _parse_header(raw: Mapping[str, Any], *, path: Path) -> FileFingerprint:
    if raw.get("type") != "header" or raw.get("version") != _AUTOSAVE_VERSION:
        raise ValueError(f"Autosave overlay {path} has an unsupported header")

    base = raw.get("base")
    if not isinstance(base, Mapping):
        raise ValueError(f"Autosave overlay {path} header has no valid base")

    size = base.get("size")
    digest = base.get("sha256")
    if (
        not isinstance(size, int)
        or size < 0
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest.lower())
    ):
        raise ValueError(f"Autosave overlay {path} header has an invalid base")

    return FileFingerprint(size=size, sha256=digest)
