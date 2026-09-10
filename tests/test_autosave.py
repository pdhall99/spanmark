"""Tests for append-only annotation autosave and JSONL checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spanmark import AnnotationSession
from spanmark._autosave import AutosaveOverlay
from spanmark._storage import FileFingerprint, fingerprint_file


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _documents() -> list[dict[str, str]]:
    return [
        {"id": "doc-1", "text": "Alice"},
        {"id": "doc-2", "text": "Bob"},
    ]


def test_overlay_recovery_uses_latest_complete_state_and_ignores_torn_tail(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    output_path.write_text('{"id":"doc-1"}\n', encoding="utf-8")
    overlay = AutosaveOverlay(output_path)
    base = fingerprint_file(output_path)

    overlay.append(
        base=base,
        document_id="doc-1",
        annotation={"spans": [], "answer": None, "flagged": True},
    )
    overlay.append(
        base=base,
        document_id="doc-1",
        annotation={"spans": [], "answer": "accept", "flagged": False},
    )
    with overlay.path.open("ab") as file:
        file.write(b'{"type":"state","id":"doc-2"')

    recovery = overlay.recover()

    assert recovery is not None
    assert recovery.base == base
    assert recovery.annotations == {
        "doc-1": {"spans": [], "answer": "accept", "flagged": False}
    }


def test_overlay_rejects_corrupt_complete_record(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    output_path.write_text('{"id":"doc-1"}\n', encoding="utf-8")
    overlay = AutosaveOverlay(output_path)
    overlay.append(
        base=fingerprint_file(output_path),
        document_id="doc-1",
        annotation={"spans": [], "answer": None, "flagged": True},
    )
    with overlay.path.open("ab") as file:
        file.write(b"not-json\n")

    with pytest.raises(ValueError, match="Invalid JSON in autosave overlay"):
        overlay.recover()


def test_overlay_refuses_to_append_against_a_different_checkpoint(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    output_path.write_text('{"id":"doc-1"}\n', encoding="utf-8")
    overlay = AutosaveOverlay(output_path)
    original = fingerprint_file(output_path)
    overlay.append(
        base=original,
        document_id="doc-1",
        annotation={"spans": [], "answer": None, "flagged": True},
    )

    changed = FileFingerprint(size=original.size + 1, sha256="0" * 64)
    with pytest.raises(RuntimeError, match="does not match"):
        overlay.append(
            base=changed,
            document_id="doc-1",
            annotation={"spans": [], "answer": "accept", "flagged": True},
        )


def test_normal_annotation_changes_do_not_rewrite_jsonl_until_checkpoint(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    initial_checkpoint = output_path.read_bytes()

    session.flag(True)
    session.decide("accept")

    assert output_path.read_bytes() == initial_checkpoint
    assert session._autosave.exists
    annotation = session.records()[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] == "accept"
    assert annotation["flagged"] is True

    session.save()

    assert not session._autosave.exists
    checkpointed = _read_jsonl(output_path)[0]["annotation"]
    assert isinstance(checkpointed, dict)
    assert checkpointed["answer"] == "accept"
    assert checkpointed["flagged"] is True
    session.close()


def test_workflow_completion_checkpoints_and_removes_overlay(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )

    session.decide("accept")
    assert session._autosave.exists

    session.decide("ignore")

    assert session.widget.complete is True
    assert not session._autosave.exists
    records = _read_jsonl(output_path)
    first = records[0]["annotation"]
    second = records[1]["annotation"]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    assert first["answer"] == "accept"
    assert second["answer"] == "ignore"
    session.close()


def test_close_checkpoints_pending_autosave(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    session.flag(True)
    autosave_path = session._autosave.path

    session.close()

    assert not autosave_path.exists()
    annotation = _read_jsonl(output_path)[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["flagged"] is True


def test_reopen_recovers_pending_autosave_and_heals_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    session.decide("accept")
    autosave_path = session._autosave.path
    assert autosave_path.exists()

    # Simulate an interrupted kernel: release the OS lock without a clean close.
    session._release_lock()

    resumed = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON"],
        output_path=output_path,
    )

    assert resumed.current_id == "doc-2"
    assert not autosave_path.exists()
    annotation = _read_jsonl(output_path)[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["answer"] == "accept"
    resumed.close()


def test_recovery_accepts_stale_overlay_after_checkpoint_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    session.decide("accept")
    autosave_path = session._autosave.path

    def fail_discard(self: AutosaveOverlay) -> None:
        raise OSError("simulated crash before overlay cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(AutosaveOverlay, "discard", fail_discard)
        with pytest.raises(OSError, match="overlay cleanup"):
            session.save()

    assert autosave_path.exists()
    session._release_lock()

    resumed = AnnotationSession.from_jsonl(
        output_path,
        labels=["PERSON"],
        output_path=output_path,
    )

    assert resumed.current_id == "doc-2"
    assert not autosave_path.exists()
    resumed.close()


def test_recovery_refuses_overlay_if_jsonl_was_modified_externally(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    session.decide("accept")
    session._release_lock()

    records = _read_jsonl(output_path)
    records[0]["text"] = "Changed outside spanmark"
    output_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="cannot be safely recovered"):
        AnnotationSession.from_jsonl(
            output_path,
            labels=["PERSON"],
            output_path=output_path,
        )


def test_large_overlay_is_checkpointed_without_public_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "annotations.jsonl"
    session = AnnotationSession(
        _documents(),
        labels=["PERSON"],
        output_path=output_path,
    )
    monkeypatch.setattr("spanmark._session.AUTOSAVE_CHECKPOINT_BYTES", 1)

    session.flag(True)

    assert not session._autosave.exists
    annotation = _read_jsonl(output_path)[0]["annotation"]
    assert isinstance(annotation, dict)
    assert annotation["flagged"] is True
    session.close()
