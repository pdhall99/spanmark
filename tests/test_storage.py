"""Tests for JSONL persistence helpers."""

import json
from pathlib import Path

from spanmark._storage import (
    atomic_write_jsonl,
    atomic_write_jsonl_with_fingerprint,
    fingerprint_file,
)


def test_atomic_write_jsonl_roundtrips_unicode_and_replaces_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "annotations.jsonl"

    atomic_write_jsonl(
        path,
        [
            {"id": "doc-1", "text": "café 😀"},
            {"id": "doc-2", "text": "東京"},
        ],
    )

    assert path.exists()
    assert list(path.parent.glob(".annotations.jsonl.*.tmp")) == []
    assert "café 😀" in path.read_text(encoding="utf-8")

    atomic_write_jsonl(
        path,
        [{"id": "doc-1", "text": "changed"}],
    )

    assert [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ] == [{"id": "doc-1", "text": "changed"}]
    assert list(path.parent.glob(".annotations.jsonl.*.tmp")) == []


def test_atomic_write_returns_fingerprint_of_exact_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "annotations.jsonl"

    result, fingerprint = atomic_write_jsonl_with_fingerprint(
        path,
        [{"id": "doc-1", "text": "café 😀"}],
    )

    assert result == path
    assert fingerprint == fingerprint_file(path)
    assert fingerprint.size == len(path.read_bytes())
