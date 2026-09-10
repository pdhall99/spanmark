"""Private document sources for in-memory and indexed JSONL inputs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from spanmark._model import Document, normalize_document


class InMemoryDocumentSource:
    """A normalized in-memory document source that preserves original records."""

    def __init__(self, documents: Sequence[Mapping[str, Any]]) -> None:
        records: list[dict[str, Any]] = []
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                raise TypeError(f"Document at index {index} must be a mapping")
            records.append(dict(document))

        normalized = tuple(
            normalize_document(record, index) for index, record in enumerate(records)
        )
        if not normalized:
            raise ValueError("documents must contain at least one document")

        ids = tuple(document.id for document in normalized)
        if len(set(ids)) != len(ids):
            raise ValueError("document ids must be unique")

        self._records = tuple(records)
        self._documents = normalized
        self.ids = ids
        self._index_by_id = {
            document_id: index for index, document_id in enumerate(ids)
        }

    def __len__(self) -> int:
        return len(self._documents)

    def __getitem__(self, index: int) -> Document:
        return self._documents[index]

    def record(self, index: int) -> Mapping[str, Any]:
        """Return the original input mapping for *index*."""
        return self._records[index]

    def index_of(self, document_id: str) -> int:
        return self._index_by_id[document_id]


class JsonlDocumentSource:
    """A JSONL source indexed by byte offset instead of retained document text."""

    def __init__(self, path: os.PathLike[str] | Path) -> None:
        self.path = Path(path)
        self._offsets: tuple[int, ...] = ()
        self._signature = (0, 0)
        self.ids: tuple[str, ...] = ()
        self._index_by_id: dict[str, int] = {}
        self.refresh()

    def __len__(self) -> int:
        return len(self._offsets)

    def __getitem__(self, index: int) -> Document:
        return normalize_document(self.record(index), index)

    def record(self, index: int) -> Mapping[str, Any]:
        """Load one original JSONL record by byte offset."""
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)

        self.check_unchanged()

        with self.path.open("rb") as file:
            file.seek(self._offsets[index])
            raw_line = file.readline()

        raw = _decode_json_line(
            raw_line,
            path=self.path,
            line_number=None,
        )
        document = normalize_document(raw, index)

        expected_id = self.ids[index]
        if document.id != expected_id:
            raise RuntimeError(
                f"JSONL source {self.path} changed while the session was open: "
                f"expected document {expected_id!r}, found {document.id!r}"
            )

        return raw

    def index_of(self, document_id: str) -> int:
        return self._index_by_id[document_id]

    def check_unchanged(self) -> None:
        """Raise if the indexed JSONL file changed since the last refresh."""
        if _file_signature(self.path) != self._signature:
            raise RuntimeError(
                f"JSONL source {self.path} changed while the session was open"
            )

    def refresh(self) -> None:
        """Rebuild byte offsets after spanmark atomically rewrites this file."""
        offsets: list[int] = []
        ids: list[str] = []
        index_by_id: dict[str, int] = {}

        with self.path.open("rb") as file:
            line_number = 0
            document_index = 0
            while True:
                offset = file.tell()
                raw_line = file.readline()
                if not raw_line:
                    break
                line_number += 1

                if not raw_line.strip():
                    continue

                raw = _decode_json_line(
                    raw_line,
                    path=self.path,
                    line_number=line_number,
                )
                document = normalize_document(raw, document_index)

                if document.id in index_by_id:
                    raise ValueError(f"document ids must be unique: {document.id!r}")

                index_by_id[document.id] = document_index
                offsets.append(offset)
                ids.append(document.id)
                document_index += 1

        if not offsets:
            raise ValueError("documents must contain at least one document")

        self._offsets = tuple(offsets)
        self.ids = tuple(ids)
        self._index_by_id = index_by_id
        self._signature = _file_signature(self.path)


def _decode_json_line(
    raw_line: bytes,
    *,
    path: Path,
    line_number: int | None,
) -> Mapping[str, Any]:
    location = f"{path} line {line_number}" if line_number is not None else str(path)

    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Invalid UTF-8 in {location}") from exc

    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {location}") from exc

    if isinstance(raw, Mapping):
        return cast(Mapping[str, Any], raw)
    raise TypeError(f"Each JSONL record in {location} must be an object")


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns
