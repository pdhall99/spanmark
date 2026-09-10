"""Immutable annotation-domain models and validation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

ANNOTATION_SOURCES = frozenset({"suggestion", "user"})


@dataclass(frozen=True, slots=True)
class Span:
    """A character span using Python half-open offsets.

    ```text
    The right-open span [2, 6):

         start=2          end=6
           ↓               ↓
    ┌─┐ ┌─┐│┌─┐ ┌─┐ ┌─┐ ┌─┐│┌─┐ ┌─┐ ┌─┐
    │0│ │1│││2│ │3│ │4│ │5│││6│ │7│ │8│
    └─┘ └─┘│└─┘ └─┘ └─┘ └─┘│└─┘ └─┘ └─┘
           └───────────────┘
           covers 2, 3, 4, 5  (length 6 − 2 = 4)
    ```
    """

    start: int
    end: int
    label: str


@dataclass(frozen=True, slots=True)
class SuggestionSpan(Span):
    """A model-provided suggestion, optionally carrying score/id metadata."""

    score: float | None = None
    id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkingSpan(Span):
    """A span as represented while annotating."""

    source: str = "user"
    id: str = ""
    score: float | None = None


@dataclass(frozen=True, slots=True)
class Document:
    """One annotation example."""

    id: str
    text: str
    meta: Mapping[str, Any]
    suggestions: tuple[SuggestionSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentState:
    """Current immutable annotation state for one document."""

    spans: tuple[WorkingSpan, ...] = ()
    answer: str = ""
    flagged: bool = False
    materialized: bool = False


def normalize_document(raw: Mapping[str, Any], index: int) -> Document:
    """Validate and normalize one input record into the annotation view."""
    if not isinstance(raw, Mapping):
        raise TypeError(f"Document at index {index} must be a mapping")
    if "id" not in raw:
        raise ValueError(f"Document at index {index} has no 'id' field")
    if "text" not in raw:
        raise ValueError(f"Document at index {index} has no 'text' field")

    raw_id = raw["id"]
    if not isinstance(raw_id, str):
        raise TypeError(f"Document at index {index} 'id' must be a string")
    if not raw_id:
        raise ValueError(f"Document at index {index} has an empty 'id' field")
    doc_id = raw_id

    raw_text = raw["text"]
    if not isinstance(raw_text, str):
        raise TypeError(f"Document {doc_id!r} 'text' must be a string")
    text = raw_text

    raw_meta = raw.get("meta")
    if raw_meta is None:
        meta: dict[str, Any] = {}
    elif isinstance(raw_meta, Mapping):
        meta = dict(raw_meta)
    else:
        raise TypeError(f"Document {doc_id!r} 'meta' must be an object or null")

    raw_suggestions = raw.get("suggestions")
    suggestions: list[dict[str, int | str | None]] | Any = (
        [] if raw_suggestions is None else raw_suggestions
    )
    if isinstance(suggestions, (str, bytes, Mapping)) or not isinstance(
        suggestions, Iterable
    ):
        raise TypeError(
            f"Document {doc_id!r} 'suggestions' must be a sequence of mappings"
        )

    return Document(
        id=doc_id,
        text=text,
        meta=meta,
        suggestions=normalize_suggestions(
            cast(Iterable[Mapping[str, Any]], suggestions),
            text=text,
        ),
    )


def normalize_suggestions(
    suggestions: Iterable[Mapping[str, Any]],
    *,
    text: str,
) -> tuple[SuggestionSpan, ...]:
    """Validate and normalize model suggestions."""
    result: list[SuggestionSpan] = []

    for i, raw in enumerate(suggestions):
        if not isinstance(raw, Mapping):
            raise TypeError(f"Suggestion {i} must be a mapping")

        start = int(raw["start"])
        end = int(raw["end"])
        label = str(raw["label"])

        _validate_offsets(start, end, text=text, context=f"suggestion {i}")

        result.append(
            SuggestionSpan(
                start=start,
                end=end,
                label=label,
                score=(float(raw["score"]) if raw.get("score") is not None else None),
                id=(str(raw["id"]) if raw.get("id") is not None else None),
            )
        )

    return tuple(sorted(result, key=lambda span: (span.start, span.end, span.label)))


def suggestion_to_working_span(
    suggestion: SuggestionSpan,
    index: int,
) -> WorkingSpan:
    """Convert a model suggestion into editable working state."""
    working_id = f"suggestion-{index}"
    if suggestion.id is not None:
        working_id = f"{working_id}:{suggestion.id}"

    return WorkingSpan(
        start=suggestion.start,
        end=suggestion.end,
        label=suggestion.label,
        source="suggestion",
        id=working_id,
        score=suggestion.score,
    )


def validate_working_spans(
    raw_spans: Iterable[Mapping[str, Any] | WorkingSpan],
    *,
    text: str,
    labels: Sequence[str],
    allow_overlaps: bool,
) -> tuple[WorkingSpan, ...]:
    """Validate browser or persisted annotation spans."""
    clean: list[WorkingSpan] = []
    allowed = set(labels)

    for i, raw in enumerate(raw_spans):
        if isinstance(raw, WorkingSpan):
            span = raw
        else:
            start = int(raw["start"])
            end = int(raw["end"])
            label = str(raw["label"])
            source = str(raw.get("source", "user"))

            span = WorkingSpan(
                start=start,
                end=end,
                label=label,
                source=source,
                id=str(raw.get("_id", raw.get("id", f"span-{i}"))),
                score=(float(raw["score"]) if raw.get("score") is not None else None),
            )

        if span.label not in allowed:
            raise ValueError(
                f"Span {i} uses unknown label {span.label!r}. "
                f"Allowed labels: {list(labels)}"
            )
        if span.source not in ANNOTATION_SOURCES:
            raise ValueError(
                f"Span {i} has invalid source {span.source!r}. "
                "Expected 'suggestion' or 'user'."
            )

        _validate_offsets(
            span.start,
            span.end,
            text=text,
            context=f"span {i}",
        )
        clean.append(span)

    ordered = tuple(
        sorted(clean, key=lambda span: (span.start, span.end, span.label, span.id))
    )

    if not allow_overlaps:
        raise_if_overlapping(ordered)

    return ordered


def raise_if_overlapping(
    spans: Iterable[Span],
    *,
    context: str = "spans",
) -> None:
    """Raise if any two spans overlap."""
    ordered = sorted(spans, key=lambda span: (span.start, span.end, span.label))
    for left, right in zip(ordered, ordered[1:]):
        if left.end > right.start:
            raise ValueError(
                f"Overlapping {context} require allow_overlaps=True: "
                f"{span_to_dict(left)} overlaps {span_to_dict(right)}"
            )


def span_to_dict(span: Span) -> dict[str, Any]:
    """Serialize the common span fields."""
    return {
        "start": span.start,
        "end": span.end,
        "label": span.label,
    }


def suggestion_to_dict(span: SuggestionSpan) -> dict[str, Any]:
    """Serialize a model suggestion."""
    result = span_to_dict(span)
    if span.score is not None:
        result["score"] = span.score
    if span.id is not None:
        result["id"] = span.id
    return result


def working_span_to_dict(span: WorkingSpan) -> dict[str, Any]:
    """Serialize a working span for the browser widget."""
    result = annotation_span_to_dict(span)
    result["_id"] = span.id
    return result


def annotation_span_to_dict(span: WorkingSpan) -> dict[str, Any]:
    """Serialize a working span into the persisted annotation schema."""
    result = span_to_dict(span)
    result["source"] = span.source
    if span.score is not None:
        result["score"] = span.score
    return result


def _validate_offsets(
    start: int,
    end: int,
    *,
    text: str,
    context: str,
) -> None:
    if not (0 <= start < end <= len(text)):
        raise ValueError(
            f"Invalid {context} offsets ({start}, {end}) for text of length {len(text)}"
        )
