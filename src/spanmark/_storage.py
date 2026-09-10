"""Small, boring JSONL persistence helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Stable identity for one complete file snapshot."""

    size: int
    sha256: str


def fingerprint_file(path: Path) -> FileFingerprint:
    """Return a content fingerprint for *path*."""
    digest = sha256()
    size = 0

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)

    return FileFingerprint(size=size, sha256=digest.hexdigest())


def atomic_write_jsonl(
    path: Path,
    records: Iterable[Mapping[str, Any]],
) -> Path:
    """Atomically replace *path* with the supplied complete JSONL dataset."""
    result, _ = atomic_write_jsonl_with_fingerprint(path, records)
    return result


def atomic_write_jsonl_with_fingerprint(
    path: Path,
    records: Iterable[Mapping[str, Any]],
) -> tuple[Path, FileFingerprint]:
    """Atomically replace *path* and return the written file fingerprint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    digest = sha256()
    size = 0

    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            tmp_path = Path(file.name)
            for record in records:
                line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
                file.write(line)
                digest.update(line)
                size += len(line)
            file.flush()
            os.fsync(file.fileno())

        os.replace(tmp_path, path)
        tmp_path = None
        _fsync_directory(path.parent)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return path, FileFingerprint(size=size, sha256=digest.hexdigest())


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync after an atomic replacement on POSIX."""
    if os.name != "posix":
        return

    try:
        file_descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(file_descriptor)
    except OSError:
        pass
    finally:
        os.close(file_descriptor)
