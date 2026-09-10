"""Tests for immutable annotation models and validation helpers."""

from dataclasses import is_dataclass

import pytest

from spanmark._model import (
    Document,
    DocumentState,
    Span,
    SuggestionSpan,
    WorkingSpan,
    annotation_span_to_dict,
    normalize_document,
    raise_if_overlapping,
    suggestion_to_dict,
    suggestion_to_working_span,
    validate_working_spans,
    working_span_to_dict,
)


@pytest.mark.parametrize(
    "model",
    [
        Span(0, 1, "A"),
        SuggestionSpan(0, 1, "A", score=0.9, id="suggestion-1"),
        WorkingSpan(0, 1, "A", source="user", id="span-1"),
        Document("doc-1", "A", {}),
        DocumentState(),
    ],
)
def test_models_are_frozen_slotted_dataclasses(model: object) -> None:
    assert is_dataclass(model)
    assert not hasattr(model, "__dict__")
    assert getattr(model, "__dataclass_params__").frozen is True


def test_normalize_document_requires_explicit_id_and_uses_suggestions_only() -> None:
    document = normalize_document(
        {
            "id": "doc-1",
            "text": "Alice joined Acme",
            "meta": {"source": "demo"},
            "spans": [{"this": "is preserved source data, not a suggestion"}],
            "suggestions": [
                {"start": 13, "end": 17, "label": "ORG", "score": 0.8},
                {"start": 0, "end": 5, "label": "PERSON", "id": "p1"},
            ],
        },
        0,
    )

    assert document.id == "doc-1"
    assert document.meta == {"source": "demo"}
    assert document.suggestions == (
        SuggestionSpan(0, 5, "PERSON", id="p1"),
        SuggestionSpan(13, 17, "ORG", score=0.8),
    )

    with pytest.raises(ValueError, match="no 'id' field"):
        normalize_document({"text": "missing id"}, 0)

    with pytest.raises(ValueError, match="empty 'id' field"):
        normalize_document({"id": "", "text": "empty id"}, 0)


def test_normalize_document_rejects_non_string_identity_text_and_bad_meta() -> None:
    with pytest.raises(TypeError, match="'id' must be a string"):
        normalize_document({"id": None, "text": "Alice"}, 0)

    with pytest.raises(TypeError, match="'text' must be a string"):
        normalize_document({"id": "doc-1", "text": None}, 0)

    with pytest.raises(TypeError, match="'text' must be a string"):
        normalize_document({"id": "doc-1", "text": 123}, 0)

    with pytest.raises(TypeError, match="'meta' must be an object or null"):
        normalize_document({"id": "doc-1", "text": "Alice", "meta": []}, 0)


def test_suggestion_conversion_preserves_metadata_and_uses_unique_browser_ids() -> None:
    suggestion = SuggestionSpan(0, 5, "PERSON", score=0.95, id="model-a")

    working = suggestion_to_working_span(suggestion, 3)

    assert working == WorkingSpan(
        0,
        5,
        "PERSON",
        source="suggestion",
        id="suggestion-3:model-a",
        score=0.95,
    )
    assert suggestion_to_dict(suggestion) == {
        "start": 0,
        "end": 5,
        "label": "PERSON",
        "score": 0.95,
        "id": "model-a",
    }
    assert working_span_to_dict(working) == {
        "start": 0,
        "end": 5,
        "label": "PERSON",
        "source": "suggestion",
        "_id": "suggestion-3:model-a",
        "score": 0.95,
    }
    assert annotation_span_to_dict(working) == {
        "start": 0,
        "end": 5,
        "label": "PERSON",
        "source": "suggestion",
        "score": 0.95,
    }

    duplicate_id = SuggestionSpan(5, 6, "PERSON", id="model-a")
    assert suggestion_to_working_span(duplicate_id, 4).id != working.id


def test_validate_working_spans_allows_overlaps_only_when_enabled() -> None:
    raw = [
        {
            "start": 0,
            "end": 5,
            "label": "OUTER",
            "source": "user",
            "_id": "outer",
        },
        {
            "start": 1,
            "end": 3,
            "label": "INNER",
            "source": "user",
            "_id": "inner",
        },
    ]

    with pytest.raises(ValueError, match="allow_overlaps=True"):
        validate_working_spans(
            raw,
            text="ABCDE",
            labels=["OUTER", "INNER"],
            allow_overlaps=False,
        )

    spans = validate_working_spans(
        raw,
        text="ABCDE",
        labels=["OUTER", "INNER"],
        allow_overlaps=True,
    )
    assert [annotation_span_to_dict(span) for span in spans] == [
        {"start": 0, "end": 5, "label": "OUTER", "source": "user"},
        {"start": 1, "end": 3, "label": "INNER", "source": "user"},
    ]


def test_validate_working_spans_rejects_unknown_source_label_and_bad_offsets() -> None:
    with pytest.raises(ValueError, match="invalid source"):
        validate_working_spans(
            [{"start": 0, "end": 1, "label": "KNOWN", "source": "model"}],
            text="A",
            labels=["KNOWN"],
            allow_overlaps=False,
        )

    with pytest.raises(ValueError, match="unknown label"):
        validate_working_spans(
            [{"start": 0, "end": 1, "label": "OTHER", "source": "user"}],
            text="A",
            labels=["KNOWN"],
            allow_overlaps=False,
        )

    with pytest.raises(ValueError, match="Invalid span 0 offsets"):
        validate_working_spans(
            [{"start": 0, "end": 2, "label": "KNOWN", "source": "user"}],
            text="A",
            labels=["KNOWN"],
            allow_overlaps=False,
        )


def test_touching_spans_do_not_count_as_overlapping() -> None:
    raise_if_overlapping(
        [
            Span(0, 2, "A"),
            Span(2, 4, "B"),
        ]
    )
