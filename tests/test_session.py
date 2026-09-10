"""Behavioural tests for the public annotation session."""

import json
from pathlib import Path

import pytest

from spanmark import AnnotationSession
from spanmark._autosave import AutosaveOverlay
from spanmark._storage import FileFingerprint


@pytest.fixture
def documents() -> list[dict[str, object]]:
    return [
        {
            "id": "doc-1",
            "text": "Alice joined Acme.",
            "meta": {"source": "demo"},
            "custom": {"preserve": True},
            "suggestions": [
                {"start": 0, "end": 5, "label": "PERSON", "score": 0.9},
                {"start": 13, "end": 17, "label": "ORG", "score": 0.8},
            ],
        },
        {
            "id": "doc-2",
            "text": "Bob moved to Rome.",
            "suggestions": [
                {"start": 0, "end": 3, "label": "PERSON"},
                {"start": 13, "end": 17, "label": "LOCATION"},
            ],
        },
    ]


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_session_immediately_creates_complete_annotated_copy(
    documents: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        documents,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )

    records = read_jsonl(output_path)
    assert [record["id"] for record in records] == ["doc-1", "doc-2"]
    assert records[0]["custom"] == {"preserve": True}
    assert records[0]["suggestions"] == documents[0]["suggestions"]
    assert records[0]["annotation"] == {
        "spans": None,
        "answer": None,
        "flagged": False,
    }
    assert records[1]["annotation"] == {
        "spans": None,
        "answer": None,
        "flagged": False,
    }
    session.close()


def test_decision_flow_autosaves_completion_and_undo(
    documents: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        documents,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )

    session.flag(True)
    session.decide("accept")

    assert session.current_id == "doc-2"
    assert session.summary() == {
        "documents": 2,
        "started": 1,
        "decided": 1,
        "accept": 1,
        "reject": 0,
        "ignore": 0,
        "flagged": 1,
        "spans": 4,
        "output_path": str(output_path),
    }

    # Normal changes are durable in the hidden overlay without rewriting the
    # complete JSONL checkpoint on every interaction.
    checkpoint_annotation = read_jsonl(output_path)[0]["annotation"]
    assert checkpoint_annotation == {
        "spans": None,
        "answer": None,
        "flagged": False,
    }
    assert session._autosave.exists

    first = session.records()[0]
    annotation = first["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] == "accept"
    assert annotation["flagged"] is True
    assert annotation["spans"] == [
        {
            "start": 0,
            "end": 5,
            "label": "PERSON",
            "source": "suggestion",
            "score": 0.9,
        },
        {
            "start": 13,
            "end": 17,
            "label": "ORG",
            "source": "suggestion",
            "score": 0.8,
        },
    ]

    session.decide("ignore")
    assert session.widget.complete is True
    assert not session._autosave.exists
    checkpointed_second = read_jsonl(output_path)[1]["annotation"]
    assert isinstance(checkpointed_second, dict)
    assert checkpointed_second["answer"] == "ignore"

    session.undo_decision()
    assert session.current_id == "doc-2"
    assert session.widget.complete is False
    assert session._autosave.exists
    second_annotation = session.records()[1]["annotation"]
    assert isinstance(second_annotation, dict)
    assert second_annotation["answer"] is None

    session.close()
    closed_second = read_jsonl(output_path)[1]["annotation"]
    assert isinstance(closed_second, dict)
    assert closed_second["answer"] is None


def test_span_edit_materializes_user_spans_and_clears_decision(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=output_path,
    )

    session.decide("accept")
    assert session.widget.complete is True

    session.widget.spans = [
        {
            "start": 0,
            "end": 5,
            "label": "PERSON",
            "source": "user",
            "_id": "user-1",
        }
    ]

    annotation = session.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation == {
        "spans": [
            {
                "start": 0,
                "end": 5,
                "label": "PERSON",
                "source": "user",
            }
        ],
        "answer": None,
        "flagged": False,
    }
    assert session.widget.complete is False
    assert session.widget.status == "Span edited — previous decision cleared."

    checkpoint_annotation = read_jsonl(output_path)[0]["annotation"]
    assert isinstance(checkpoint_annotation, dict)
    assert checkpoint_annotation["answer"] == "accept"

    session.close()
    assert read_jsonl(output_path)[0]["annotation"] == annotation


def test_resume_uses_annotated_output_as_input_and_starts_first_undecided(
    documents: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        documents,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )
    session.decide("accept")
    session.close()

    resumed = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )

    assert resumed.current_id == "doc-2"
    annotation = resumed.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] == "accept"
    assert resumed.widget.can_undo is True

    resumed.undo_decision()
    assert resumed.current_id == "doc-1"
    annotation = resumed.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] is None
    resumed.close()


def test_deleted_suggestions_stay_deleted_after_resume(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [
            {
                "id": "doc-1",
                "text": "Alice",
                "suggestions": [{"start": 0, "end": 5, "label": "PERSON"}],
            }
        ],
        labels=["PERSON"],
        output_path=output_path,
    )

    assert len(session.widget.spans) == 1
    session.widget.spans = []
    session.close()

    persisted = read_jsonl(output_path)[0]["annotation"]
    assert persisted == {"spans": [], "answer": None, "flagged": False}

    resumed = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON"],
        output_path=output_path,
    )
    assert resumed.widget.spans == []
    resumed.close()


def test_accepting_zero_span_example_is_decided(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Nothing here."}],
        labels=["PERSON"],
        output_path=output_path,
    )

    session.decide("accept")

    annotation = read_jsonl(output_path)[0]["annotation"]
    assert annotation == {"spans": [], "answer": "accept", "flagged": False}
    assert session.widget.complete is True
    session.close()


def test_jsonl_input_writes_copy_and_preserves_arbitrary_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "documents.jsonl"
    input_records = [
        {
            "id": "doc-1",
            "text": "Alice joined Acme.",
            "external": {"anything": [1, 2]},
            "suggestions": [{"start": 0, "end": 5, "label": "PERSON"}],
        },
        {"id": "doc-2", "text": "Bob moved to Rome."},
    ]
    input_path.write_text(
        "\n".join(json.dumps(record) for record in input_records) + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "annotations.jsonl"

    session = AnnotationSession.from_jsonl(
        input_path,
        labels=["PERSON"],
        output_path=output_path,
    )

    assert input_path.read_text(encoding="utf-8") == (
        "\n".join(json.dumps(record) for record in input_records) + "\n"
    )
    assert read_jsonl(output_path)[0]["external"] == {"anything": [1, 2]}
    session.close()


def test_existing_different_output_is_refused(tmp_path: Path) -> None:
    input_path = tmp_path / "documents.jsonl"
    input_path.write_text('{"id":"doc-1","text":"Alice"}\n', encoding="utf-8")
    output_path = tmp_path / "annotations.jsonl"
    output_path.write_text("important existing work\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        AnnotationSession.from_jsonl(
            input_path,
            labels=["PERSON"],
            output_path=output_path,
        )

    assert output_path.read_text(encoding="utf-8") == "important existing work\n"


def test_in_memory_session_refuses_existing_output(
    documents: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    output_path.write_text("do not overwrite\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        AnnotationSession(
            documents,
            labels=["PERSON", "ORG", "LOCATION"],
            output_path=output_path,
        )


def test_output_path_is_exclusively_locked_until_close(
    documents: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    first = AnnotationSession(
        documents,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )

    with pytest.raises(
        RuntimeError, match="already in use by another spanmark session"
    ):
        AnnotationSession.from_jsonl(
            output_path,
            labels=["PERSON", "ORG", "LOCATION"],
            output_path=output_path,
        )

    first.close()

    second = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON", "ORG", "LOCATION"],
        output_path=output_path,
    )
    second.close()


def test_context_manager_releases_output_lock(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"

    with AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=output_path,
    ) as session:
        assert session.current_id == "doc-1"

    with pytest.raises(RuntimeError, match="session is closed"):
        session.decide("accept")

    reopened = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON"],
        output_path=output_path,
    )
    reopened.close()


def test_session_rejects_overlapping_suggestions_unless_enabled(tmp_path: Path) -> None:
    documents = [
        {
            "id": "doc-1",
            "text": "ABCDE",
            "suggestions": [
                {"start": 0, "end": 5, "label": "OUTER"},
                {"start": 1, "end": 3, "label": "INNER"},
            ],
        }
    ]

    with pytest.raises(ValueError, match="allow_overlaps=True"):
        AnnotationSession(
            documents,
            labels=["OUTER", "INNER"],
            output_path=tmp_path / "classic.jsonl",
        )

    session = AnnotationSession(
        documents,
        labels=["OUTER", "INNER"],
        output_path=tmp_path / "overlap.jsonl",
        allow_overlaps=True,
    )
    assert len(session.widget.spans) == 2
    session.close()


def test_flagged_review_resolves_items_in_dataset_order(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [
            {"id": "doc-1", "text": "Alice"},
            {"id": "doc-2", "text": "Bob"},
        ],
        labels=["PERSON"],
        output_path=output_path,
    )

    session.flag(True)
    session.decide("accept")
    session.flag(True)
    session.decide("ignore")

    assert session.widget.complete is True
    assert session.widget.flagged_count == 2
    assert session.widget.reviewing_flagged is False

    session.widget.event = {"type": "review_flagged", "nonce": 1}

    assert session.widget.reviewing_flagged is True
    assert session.current_id == "doc-1"
    assert session.widget.can_undo is False

    session.decide("reject")
    assert session.current_id == "doc-1"
    assert session.records()[0]["annotation"]["answer"] == "reject"

    session.flag(False)
    assert session.current_id == "doc-2"
    assert session.widget.reviewing_flagged is True
    assert session.widget.flagged_count == 1

    session.widget.spans = [
        {
            "start": 0,
            "end": 3,
            "label": "PERSON",
            "source": "user",
            "_id": "user-1",
        }
    ]
    assert session.widget.complete is False
    assert session.widget.answer == ""

    session.flag(False)
    assert session.widget.flagged is True
    assert session.current_id == "doc-2"
    assert session.widget.status == (
        "Choose Accept, Reject, or Ignore before clearing Flag."
    )

    session.decide("accept")
    assert session.widget.complete is True
    assert session.current_id == "doc-2"

    session.flag(False)
    assert session.widget.reviewing_flagged is False
    assert session.widget.flagged_count == 0
    assert session.widget.complete is True
    assert session.widget.status == "Flagged review complete."
    session.close()


def test_flagged_review_is_unavailable_before_main_pass_completes(
    tmp_path: Path,
) -> None:
    session = AnnotationSession(
        [
            {"id": "doc-1", "text": "Alice"},
            {"id": "doc-2", "text": "Bob"},
        ],
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )
    session.flag(True)

    session.widget.event = {"type": "review_flagged", "nonce": 1}

    assert session.widget.reviewing_flagged is False
    assert session.current_id == "doc-1"
    assert session.widget.status == (
        "Finish the main annotation pass before reviewing flags."
    )
    session.close()


def test_reopen_complete_jsonl_returns_to_completion_with_remaining_flags(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [
            {"id": "doc-1", "text": "Alice"},
            {"id": "doc-2", "text": "Bob"},
        ],
        labels=["PERSON"],
        output_path=output_path,
    )

    session.flag(True)
    session.decide("accept")
    session.flag(True)
    session.decide("accept")
    session.widget.event = {"type": "review_flagged", "nonce": 1}
    session.flag(False)
    assert session.current_id == "doc-2"
    session.close()

    resumed = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON"],
        output_path=output_path,
    )

    assert resumed.widget.complete is True
    assert resumed.widget.reviewing_flagged is False
    assert resumed.widget.flagged_count == 1

    resumed.widget.event = {"type": "review_flagged", "nonce": 2}
    assert resumed.widget.reviewing_flagged is True
    assert resumed.current_id == "doc-2"
    resumed.close()


def test_completion_checkpoint_failure_keeps_durable_autosave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=output_path,
    )

    def fail_checkpoint(
        *args: object, **kwargs: object
    ) -> tuple[Path, FileFingerprint]:
        raise OSError("checkpoint disk error")

    monkeypatch.setattr(
        "spanmark._session.atomic_write_jsonl_with_fingerprint",
        fail_checkpoint,
    )

    session.decide("accept")

    assert session.widget.complete is True
    assert session._autosave.exists
    assert session.widget.status.startswith("All examples are complete.")
    assert "Autosaved, but JSONL checkpoint failed" in session.widget.status
    annotation = session.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] == "accept"

    monkeypatch.undo()
    session.close()
    assert not session._autosave.exists


def test_orphaned_autosave_is_not_silently_overwritten(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    overlay = AutosaveOverlay(output_path)
    overlay.path.write_text(
        '{"type":"header","version":1,"base":{"size":0,"sha256":"' + "0" * 64 + '"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Recovery autosave"):
        AnnotationSession(
            [{"id": "doc-1", "text": "Alice"}],
            labels=["PERSON"],
            output_path=output_path,
        )

    assert overlay.path.exists()


def test_decision_save_failure_does_not_commit_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [
            {"id": "doc-1", "text": "Alice"},
            {"id": "doc-2", "text": "Bob"},
        ],
        labels=["PERSON"],
        output_path=output_path,
    )
    before = session.records()

    def fail_append(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("spanmark._session.AutosaveOverlay.append", fail_append)

    with pytest.raises(OSError, match="disk full"):
        session.decide("accept")

    assert session.current_id == "doc-1"
    assert session.widget.answer == ""
    assert session.widget.complete is False
    assert session.records() == before
    session.close()


def test_invalid_browser_span_is_reverted_with_visible_status(tmp_path: Path) -> None:
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )

    session.widget.spans = [
        {
            "start": 0,
            "end": 99,
            "label": "PERSON",
            "source": "user",
            "_id": "bad-span",
        }
    ]

    assert session.widget.spans == []
    assert session.widget.status.startswith("Span edit rejected:")
    annotation = session.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["spans"] is None
    session.close()


def test_browser_span_save_failure_reverts_widget_and_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )

    def fail_append(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("spanmark._session.AutosaveOverlay.append", fail_append)

    session.widget.spans = [
        {
            "start": 0,
            "end": 5,
            "label": "PERSON",
            "source": "user",
            "_id": "user-1",
        }
    ]

    assert session.widget.spans == []
    assert session.widget.status == "Could not save span edit: disk full"
    annotation = session.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["spans"] is None
    session.close()


def test_external_jsonl_change_is_surfaced_and_browser_edit_is_reverted(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "documents.jsonl"
    input_path.write_text('{"id":"doc-1","text":"Alice"}\n', encoding="utf-8")
    session = AnnotationSession.from_jsonl(
        input_path,
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )

    input_path.write_text('{"id":"doc-1","text":"ALICE!"}\n', encoding="utf-8")
    session.widget.spans = [
        {
            "start": 0,
            "end": 5,
            "label": "PERSON",
            "source": "user",
            "_id": "user-1",
        }
    ]

    assert session.widget.spans == []
    assert session.widget.status.startswith("Could not save span edit:")
    assert "changed while the session was open" in session.widget.status
    session.close()


def test_external_output_change_is_surfaced_before_autosave(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=output_path,
    )
    output_path.write_text(
        '{"id":"doc-1","text":"changed outside spanmark"}\n',
        encoding="utf-8",
    )

    session.widget.spans = [
        {
            "start": 0,
            "end": 5,
            "label": "PERSON",
            "source": "user",
            "_id": "user-1",
        }
    ]

    assert session.widget.spans == []
    assert session.widget.status.startswith("Could not save span edit:")
    assert "JSONL output" in session.widget.status
    assert "changed while the session was open" in session.widget.status
    session._release_lock()


def test_browser_flag_save_failure_reverts_widget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )

    def fail_append(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("spanmark._session.AutosaveOverlay.append", fail_append)

    session.widget.flagged = True

    assert session.widget.flagged is False
    assert session.widget.flagged_count == 0
    assert session.widget.status == "Could not save Flag change: disk full"
    session.close()


def test_browser_decision_save_failure_surfaces_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AnnotationSession(
        [{"id": "doc-1", "text": "Alice"}],
        labels=["PERSON"],
        output_path=tmp_path / "annotations.jsonl",
    )

    def fail_append(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("spanmark._session.AutosaveOverlay.append", fail_append)

    session.widget.event = {"type": "decision", "answer": "accept", "nonce": 1}

    assert session.widget.answer == ""
    assert session.widget.complete is False
    assert session.widget.status == "Could not apply action: disk full"
    session.close()
