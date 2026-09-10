"""Tests for private in-memory and indexed JSONL document sources."""

import json
from pathlib import Path

import pytest

from spanmark._source import InMemoryDocumentSource, JsonlDocumentSource


def test_in_memory_source_preserves_original_record_fields() -> None:
    source = InMemoryDocumentSource(
        [
            {
                "id": "doc-1",
                "text": "Alice joined Acme.",
                "custom": {"keep": "me"},
                "suggestions": [{"start": 0, "end": 5, "label": "PERSON"}],
            }
        ]
    )

    assert source.ids == ("doc-1",)
    assert source[0].text == "Alice joined Acme."
    assert source.record(0)["custom"] == {"keep": "me"}


def test_jsonl_source_indexes_records_and_loads_on_demand(tmp_path: Path) -> None:
    path = tmp_path / "documents.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "doc-1",
                        "text": "Alice joined Acme.",
                        "custom": [1, 2, 3],
                        "suggestions": [
                            {"start": 0, "end": 5, "label": "PERSON"},
                        ],
                    }
                ),
                "",
                json.dumps({"id": "doc-2", "text": "Bob moved to Rome."}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    source = JsonlDocumentSource(path)

    assert len(source) == 2
    assert source.ids == ("doc-1", "doc-2")
    assert source.index_of("doc-2") == 1
    assert source[0].text == "Alice joined Acme."
    assert source.record(0)["custom"] == [1, 2, 3]
    assert source[1].id == "doc-2"


def test_jsonl_source_requires_objects_explicit_ids_and_unique_ids(
    tmp_path: Path,
) -> None:
    duplicate_path = tmp_path / "duplicates.jsonl"
    duplicate_path.write_text(
        '{"id":"same","text":"one"}\n{"id":"same","text":"two"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="document ids must be unique"):
        JsonlDocumentSource(duplicate_path)

    missing_id = tmp_path / "missing-id.jsonl"
    missing_id.write_text('{"text":"one"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="no 'id' field"):
        JsonlDocumentSource(missing_id)

    string_record = tmp_path / "string.jsonl"
    string_record.write_text('"plain string"\n', encoding="utf-8")

    with pytest.raises(TypeError, match="must be an object"):
        JsonlDocumentSource(string_record)


def test_jsonl_source_reports_bad_json_line_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"ok","text":"one"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"line 2$"):
        JsonlDocumentSource(path)


def test_jsonl_source_detects_external_changes_and_can_refresh(tmp_path: Path) -> None:
    path = tmp_path / "documents.jsonl"
    path.write_text('{"id":"doc-1","text":"original"}\n', encoding="utf-8")
    source = JsonlDocumentSource(path)

    path.write_text('{"id":"doc-1","text":"changed text"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed while the session was open"):
        source[0]

    source.refresh()
    assert source[0].text == "changed text"
