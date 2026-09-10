"""Public annotation-session orchestration."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, TypeAlias, cast

from filelock import FileLock, Timeout
from IPython.display import display
from typing_extensions import Self

from spanmark._autosave import AUTOSAVE_CHECKPOINT_BYTES, AutosaveOverlay
from spanmark._model import (
    Document,
    DocumentState,
    WorkingSpan,
    annotation_span_to_dict,
    normalize_document,
    suggestion_to_working_span,
    validate_working_spans,
    working_span_to_dict,
)
from spanmark._source import InMemoryDocumentSource, JsonlDocumentSource
from spanmark._storage import (
    FileFingerprint,
    atomic_write_jsonl_with_fingerprint,
    fingerprint_file,
)
from spanmark._widget import SpanmarkWidget

_DocumentSource: TypeAlias = InMemoryDocumentSource | JsonlDocumentSource


class AnnotationSession:
    """A one-way span annotation session.

    spanmark keeps a complete annotated JSONL checkpoint at `output_path`.
    Annotation changes are durably autosaved to a small hidden state overlay and
    periodically checkpointed back into the JSONL. A clean close, explicit
    `save()`, and workflow completion leave `output_path` fully current.

    Every output record keeps the original input fields and gains a reserved
    `annotation` object. To resume later, open that annotated JSONL file with
    `from_jsonl()` and use the same path as `output_path`.

    Args:
        documents: Input documents to annotate. Each mapping must contain an explicit,
            non-empty `id` and a `text` field, and document IDs must be unique.
            Optional model pre-annotations belong under `suggestions`. Other input
            fields are preserved in the output dataset.
        labels: Non-empty sequence of unique span labels. Every suggestion and persisted
            annotation span must use one of these labels.
        output_path: JSONL annotated-dataset destination. The path must not already
            exist for an in-memory session. spanmark creates it immediately, durably
            autosaves annotation changes, and holds an exclusive lock for the path until
            `close()` is called.
        trim_whitespace: If true (default), remove leading and trailing whitespace
            from newly selected text before creating a span. A selection containing only
            whitespace is ignored.
        allow_overlaps: If false (default), reject overlapping or nested spans and use
            the classic inline-highlight UI. If true, allow overlaps/nesting and use the
            colored annotation-rail UI.

    Attributes:
        labels: Validated annotation labels, stored as a tuple of strings.
        output_path: Path to the annotated JSONL dataset.
        allow_overlaps: Whether overlapping and nested spans are allowed.
        widget: Annotation widget associated with the session.

    Note:
        During the main pass, Accept, Reject, and Ignore autosave and advance to the
        next undecided document. Flag is an independent bookmark. Once every document
        is decided, flagged documents can be reviewed in dataset order; clearing a
        flag resolves that review item and advances to the next flagged document.
    """

    ANSWERS = frozenset({"accept", "reject", "ignore"})

    def __init__(
        self,
        documents: Sequence[Mapping[str, Any]],
        labels: Sequence[str],
        output_path: os.PathLike[str] | Path,
        *,
        trim_whitespace: bool = True,
        allow_overlaps: bool = False,
    ) -> None:
        source = InMemoryDocumentSource(documents)
        self._initialize(
            source=source,
            labels=labels,
            output_path=output_path,
            trim_whitespace=trim_whitespace,
            allow_overlaps=allow_overlaps,
            source_is_output=False,
        )

    @classmethod
    def from_jsonl(
        cls,
        path: os.PathLike[str] | Path,
        labels: Sequence[str],
        output_path: os.PathLike[str] | Path,
        *,
        trim_whitespace: bool = True,
        allow_overlaps: bool = False,
    ) -> Self:
        """Create a session from a JSONL dataset.

        For a new annotation run, `path` and `output_path` are different and
        `output_path` must not already exist. spanmark immediately writes a
        complete annotated copy there.

        To resume, pass the previous annotated output as both `path` and
        `output_path`. spanmark recovers any pending hidden autosave state,
        checkpoints it into the JSONL, and starts at the first record whose
        annotation decision is still unset. If every record is already decided,
        it opens the completion state, where any remaining flags can be reviewed.

        Args:
            path: JSONL input dataset. Each non-empty line must contain an object with
                an explicit, non-empty `id` and `text` field, and IDs must be
                unique within the file.
            labels: Non-empty sequence of unique span labels. Every suggestion and
                persisted annotation span must use one of these labels.
            output_path: JSONL annotated-dataset destination. For a new run this must be a
                different, non-existing path. To resume, pass the same annotated
                JSONL path for both `path` and `output_path`.
            trim_whitespace: If true (default), remove leading and trailing whitespace
                from newly selected text before creating a span. A selection containing
                only whitespace is ignored.
            allow_overlaps: If false (default), reject overlapping or nested spans and
                use the classic inline-highlight UI. If true, allow overlaps/nesting
                and use the colored annotation-rail UI.
        """
        input_path = Path(path)
        output = Path(output_path)
        source_is_output = input_path.resolve() == output.resolve()

        if not source_is_output and output.exists():
            raise FileExistsError(
                f"{output} already exists. To resume it, pass that file as both "
                "the JSONL input and output_path; otherwise choose a new output_path."
            )

        source = JsonlDocumentSource(input_path)
        session = cls.__new__(cls)
        session._initialize(
            source=source,
            labels=labels,
            output_path=output,
            trim_whitespace=trim_whitespace,
            allow_overlaps=allow_overlaps,
            source_is_output=source_is_output,
        )
        return session

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
            return

        try:
            self.close()
        except Exception as close_error:
            note = f"spanmark also failed to checkpoint while closing: {close_error}"
            if hasattr(exc_value, "add_note"):
                exc_value.add_note(note)
            else:
                warnings.warn(note, RuntimeWarning, stacklevel=2)

    def close(self) -> None:
        """Checkpoint pending autosaves and release the output-path lock."""
        if self._closed:
            return

        try:
            if self._autosave.exists:
                self._checkpoint()
        finally:
            self._release_lock()

    def display(self) -> None:
        """Display the annotation UI once."""
        self._ensure_open()
        display(self.widget)

    @property
    def index(self) -> int:
        """The index of the current document."""
        return self._index

    @property
    def current_id(self) -> str:
        """The identifier of the current document."""
        return self._source.ids[self._index]

    def decide(self, answer: str) -> None:
        """Submit an Accept/Reject/Ignore decision for the current document."""
        self._ensure_open()
        answer = str(answer).lower()
        if answer not in self.ANSWERS:
            raise ValueError(
                f"answer must be one of {sorted(self.ANSWERS)}, got {answer!r}"
            )

        doc_id = self.current_id
        state = replace(
            self._state[doc_id],
            answer=answer,
            materialized=True,
        )
        decision_history = [
            saved_id for saved_id in self._decision_history if saved_id != doc_id
        ]
        decision_history.append(doc_id)

        self._append_state(doc_id, state)
        self._state[doc_id] = state
        self._decision_history = decision_history

        self._loading = True
        try:
            self.widget.answer = answer
            self._sync_summary_traits()
        finally:
            self._loading = False

        if self._reviewing_flagged:
            status = "Decision updated — clear Flag when review is resolved."
            self.widget.status = self._checkpoint_warning_if_large() or status
            return

        next_index = self._next_undecided_index(self._index)
        if next_index is not None:
            self._index = next_index
            self._load_current()
            warning = self._checkpoint_warning_if_large()
            if warning is not None:
                self.widget.status = warning
        else:
            self._sync_summary_traits()
            self._checkpoint_with_status("All examples are complete.")

    def undo_decision(self) -> None:
        """Undo and reopen the immediately previous submitted example."""
        self._ensure_open()
        if self._reviewing_flagged:
            self.widget.status = (
                "Previous-decision Undo is unavailable during flagged review."
            )
            return
        if not self._decision_history:
            self.widget.status = "No previous submitted decision to undo."
            return

        doc_id = self._decision_history[-1]
        state = replace(
            self._state[doc_id],
            answer="",
            materialized=True,
        )
        decision_history = self._decision_history[:-1]

        self._append_state(doc_id, state)
        self._state[doc_id] = state
        self._decision_history = decision_history
        self._index = self._source.index_of(doc_id)

        self._load_current()
        status = "Previous decision undone — review this example again."
        self.widget.status = self._checkpoint_warning_if_large() or status

    def flag(self, value: bool = True) -> None:
        """Set or clear the flag on the current document."""
        self._ensure_open()
        new_value = bool(value)
        doc_id = self.current_id
        current_state = self._state[doc_id]

        if (
            self._reviewing_flagged
            and not new_value
            and current_state.answer not in self.ANSWERS
        ):
            self._loading = True
            try:
                self.widget.flagged = True
            finally:
                self._loading = False
            self.widget.status = (
                "Choose Accept, Reject, or Ignore before clearing Flag."
            )
            return

        state = replace(
            current_state,
            flagged=new_value,
            materialized=True,
        )

        self._append_state(doc_id, state)
        self._state[doc_id] = state

        self._loading = True
        try:
            self.widget.flagged = new_value
            self._sync_summary_traits()
        finally:
            self._loading = False

        if self._reviewing_flagged and not new_value:
            next_index = self._first_flagged_index()
            if next_index is not None:
                self._index = next_index
                self._load_current()
                status = (
                    "Review flagged examples — clear Flag when this item is resolved."
                )
                self.widget.status = self._checkpoint_warning_if_large() or status
            else:
                self._reviewing_flagged = False
                self._sync_summary_traits()
                self._checkpoint_with_status("Flagged review complete.")
            return

        warning = self._checkpoint_warning_if_large()
        if warning is not None:
            self.widget.status = warning

    def records(self) -> list[dict[str, Any]]:
        """Return the complete current annotated dataset."""
        self._ensure_open()
        return list(self._iter_records())

    def save(self) -> Path:
        """Checkpoint all current annotation state into `output_path`."""
        self._ensure_open()
        return self._checkpoint()

    def summary(self) -> dict[str, Any]:
        """Return compact annotation progress statistics."""
        return {
            "documents": len(self._source),
            "started": sum(state.materialized for state in self._state.values()),
            "decided": self._decided_count(),
            "accept": self._answer_count("accept"),
            "reject": self._answer_count("reject"),
            "ignore": self._answer_count("ignore"),
            "flagged": self._flagged_count(),
            "spans": sum(len(state.spans) for state in self._state.values()),
            "output_path": str(self.output_path),
        }

    def _initialize(
        self,
        *,
        source: _DocumentSource,
        labels: Sequence[str],
        output_path: os.PathLike[str] | Path,
        trim_whitespace: bool,
        allow_overlaps: bool,
        source_is_output: bool,
    ) -> None:
        if not labels:
            raise ValueError("labels must contain at least one label")

        self.labels = tuple(str(label) for label in labels)
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels must be unique")

        self.output_path = Path(output_path)
        self.allow_overlaps = bool(allow_overlaps)
        self._source = source
        self._source_is_output = bool(source_is_output)
        self._state: dict[str, DocumentState] = {}
        self._loading = False
        self._index = 0
        self._closed = False
        self._reviewing_flagged = False
        self._autosave = AutosaveOverlay(self.output_path)
        self._output_fingerprint: FileFingerprint | None = None
        self._output_signature: tuple[int, int] | None = None

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.output_path.with_name(f".{self.output_path.name}.lock")
        self._output_lock = FileLock(lock_path)

        try:
            self._output_lock.acquire(timeout=0)
        except Timeout as exc:
            self._closed = True
            raise RuntimeError(
                f"{self.output_path} is already in use by another spanmark session"
            ) from exc

        try:
            if not self._source_is_output and self.output_path.exists():
                raise FileExistsError(
                    f"{self.output_path} already exists. To resume it, pass that "
                    "JSONL file as both input and output_path; otherwise choose a "
                    "new output_path."
                )
            if not self._source_is_output and self._autosave.exists:
                raise RuntimeError(
                    f"Recovery autosave {self._autosave.path} exists without a "
                    f"resumable output at {self.output_path}. Move or remove the "
                    "orphaned autosave before starting a new session."
                )

            if self._source_is_output:
                if not isinstance(self._source, JsonlDocumentSource):
                    raise RuntimeError("Only a JSONL source can be its own output")
                self._source.refresh()
                self._set_output_identity(fingerprint_file(self.output_path))

            self._load_states()
            if self._source_is_output and self._autosave.exists:
                self._recover_autosave()

            self._index = self._resume_index()
            self._decision_history = self._resume_decision_history()

            self.widget = SpanmarkWidget(
                labels=list(self.labels),
                trim_whitespace=trim_whitespace,
                allow_overlaps=self.allow_overlaps,
            )
            self.widget.observe(self._on_spans, names="spans")
            self.widget.observe(self._on_flagged, names="flagged")
            self.widget.observe(self._on_event, names="event")

            self._load_current()

            # A new session starts with a complete JSONL checkpoint. On resume,
            # this also folds any recovered autosave overlay back into the file.
            self._checkpoint()
        except BaseException:
            self._release_lock()
            raise

    def _load_states(self) -> None:
        for index, expected_id in enumerate(self._source.ids):
            raw = self._source.record(index)
            document = normalize_document(raw, index)
            if document.id != expected_id:
                raise RuntimeError(
                    f"Document source index expected {expected_id!r}, "
                    f"found {document.id!r}"
                )
            self._state[document.id] = self._state_from_record(document, raw)

    def _state_from_record(
        self,
        document: Document,
        raw: Mapping[str, Any],
    ) -> DocumentState:
        suggestion_spans = tuple(
            suggestion_to_working_span(suggestion, index)
            for index, suggestion in enumerate(document.suggestions)
        )
        suggestion_spans = validate_working_spans(
            suggestion_spans,
            text=document.text,
            labels=self.labels,
            allow_overlaps=self.allow_overlaps,
        )

        annotation = raw.get("annotation")
        if annotation is None:
            return DocumentState(spans=suggestion_spans)
        if not isinstance(annotation, Mapping):
            raise TypeError(f"Document {document.id!r} 'annotation' must be an object")

        raw_answer = annotation.get("answer")
        if raw_answer is None:
            answer = ""
        elif isinstance(raw_answer, str) and raw_answer in self.ANSWERS:
            answer = raw_answer
        else:
            raise ValueError(
                f"Document {document.id!r} annotation answer must be one of "
                f"{sorted(self.ANSWERS)} or null"
            )

        raw_flagged = annotation.get("flagged", False)
        if not isinstance(raw_flagged, bool):
            raise TypeError(
                f"Document {document.id!r} annotation flagged must be a boolean"
            )

        raw_spans = annotation.get("spans")
        if raw_spans is None:
            if answer or raw_flagged:
                raise ValueError(
                    f"Document {document.id!r} annotation spans cannot be null "
                    "once a decision or flag has been recorded"
                )
            return DocumentState(spans=suggestion_spans)

        if isinstance(raw_spans, (str, bytes, Mapping)) or not isinstance(
            raw_spans, Sequence
        ):
            raise TypeError(
                f"Document {document.id!r} annotation spans must be a list or null"
            )

        persisted_spans = cast(
            Sequence[Mapping[str, Any] | WorkingSpan],
            raw_spans,
        )
        spans = validate_working_spans(
            persisted_spans,
            text=document.text,
            labels=self.labels,
            allow_overlaps=self.allow_overlaps,
        )
        return DocumentState(
            spans=spans,
            answer=answer,
            flagged=raw_flagged,
            materialized=True,
        )

    def _recover_autosave(self) -> None:
        recovery = self._autosave.recover()
        if recovery is None:
            return

        current_fingerprint = self._output_fingerprint
        if current_fingerprint is None:
            raise RuntimeError("Cannot recover autosave without a JSONL checkpoint")

        recovered_states: dict[str, DocumentState] = {}
        for document_id, annotation in recovery.annotations.items():
            if document_id not in self._state:
                raise RuntimeError(
                    f"Autosave overlay {self._autosave.path} refers to unknown "
                    f"document {document_id!r}"
                )
            index = self._source.index_of(document_id)
            document = self._source[index]
            recovered_states[document_id] = self._state_from_record(
                document,
                {"annotation": annotation},
            )

        if recovery.base == current_fingerprint:
            self._state.update(recovered_states)
            return

        if all(
            self._state[document_id] == state
            for document_id, state in recovered_states.items()
        ):
            # A checkpoint may have been atomically replaced before overlay cleanup.
            # Discarding the stale overlay is safe only because every overlay entry
            # is a complete per-document annotation state, not a patch: if every
            # recovered state is already present in the JSONL, the overlay contains
            # no additional information that could be lost. If overlay records ever
            # become partial updates, this recovery rule must be redesigned.
            return

        raise RuntimeError(
            f"Autosave overlay {self._autosave.path} was based on a different "
            "JSONL checkpoint and cannot be safely recovered. The output may have "
            "been modified outside spanmark."
        )

    def _current_doc(self) -> Document:
        return self._source[self._index]

    def _decided_count(self) -> int:
        return sum(state.answer in self.ANSWERS for state in self._state.values())

    def _answer_count(self, answer: str) -> int:
        return sum(state.answer == answer for state in self._state.values())

    def _flagged_count(self) -> int:
        return sum(state.flagged for state in self._state.values())

    def _is_complete(self) -> bool:
        return self._decided_count() == len(self._source)

    def _sync_summary_traits(self) -> None:
        self.widget.decided_count = self._decided_count()
        self.widget.accept_count = self._answer_count("accept")
        self.widget.reject_count = self._answer_count("reject")
        self.widget.ignore_count = self._answer_count("ignore")
        self.widget.flagged_count = self._flagged_count()
        self.widget.complete = self._is_complete()
        self.widget.reviewing_flagged = self._reviewing_flagged
        self.widget.can_undo = (
            bool(self._decision_history) and not self._reviewing_flagged
        )

    def _resume_index(self) -> int:
        for index, document_id in enumerate(self._source.ids):
            if self._state[document_id].answer not in self.ANSWERS:
                return index
        return len(self._source) - 1

    def _resume_decision_history(self) -> list[str]:
        current_id = self._source.ids[self._index]
        current_decided = self._state[current_id].answer in self.ANSWERS
        stop = self._index + 1 if current_decided else self._index

        # JSONL stores decisions but not action chronology. Reconstructing history
        # in dataset order matches the normal one-way pass, but cannot reproduce
        # arbitrary pre-close edit/redecision order exactly.
        return [
            document_id
            for document_id in self._source.ids[:stop]
            if self._state[document_id].answer in self.ANSWERS
        ]

    def _next_undecided_index(self, after: int) -> int | None:
        for index in range(after + 1, len(self._source)):
            document_id = self._source.ids[index]
            if self._state[document_id].answer not in self.ANSWERS:
                return index
        return None

    def _first_flagged_index(self) -> int | None:
        for index, document_id in enumerate(self._source.ids):
            if self._state[document_id].flagged:
                return index
        return None

    def _start_flagged_review(self) -> None:
        if not self._is_complete():
            self.widget.status = (
                "Finish the main annotation pass before reviewing flags."
            )
            return

        first_index = self._first_flagged_index()
        if first_index is None:
            self.widget.status = "There are no flagged examples to review."
            return

        self._reviewing_flagged = True
        self._index = first_index
        self._load_current()
        self.widget.status = (
            "Review flagged examples — clear Flag when this item is resolved."
        )

    def _load_current(self) -> None:
        document = self._current_doc()
        self._set_widget_document(document, self._state[document.id])

    def _set_widget_document(
        self,
        document: Document,
        state: DocumentState,
        *,
        status: str = "",
    ) -> None:
        self._loading = True
        try:
            self.widget.doc_id = document.id
            self.widget.text = document.text
            self.widget.index = self._index
            self.widget.total = len(self._source)
            self._set_widget_annotation_state(state, status=status)
        finally:
            self._loading = False

    def _set_widget_annotation_state(
        self,
        state: DocumentState,
        *,
        status: str = "",
    ) -> None:
        self.widget.spans = [working_span_to_dict(span) for span in state.spans]
        self.widget.answer = state.answer
        self.widget.flagged = state.flagged
        self._sync_summary_traits()
        self.widget.status = status

    def _restore_current_annotation_state(self, *, status: str) -> None:
        self._loading = True
        try:
            self._set_widget_annotation_state(
                self._state[self.current_id],
                status=status,
            )
        finally:
            self._loading = False

    def _on_spans(self, change: Mapping[str, Any]) -> None:
        if self._loading or self._closed:
            return

        doc_id = self.current_id
        previous_state = self._state[doc_id]

        try:
            spans = validate_working_spans(
                change["new"],
                text=self.widget.text,
                labels=self.labels,
                allow_overlaps=self.allow_overlaps,
            )
        except Exception as exc:
            self._restore_current_annotation_state(
                status=f"Span edit rejected: {exc}",
            )
            return

        state = replace(
            previous_state,
            spans=spans,
            materialized=True,
        )
        decision_history = self._decision_history
        status = ""

        # A decision certifies the exact current span set. Any edit invalidates
        # the previous decision while preserving Flag.
        if state.answer in self.ANSWERS:
            state = replace(state, answer="")
            decision_history = [
                saved_id for saved_id in self._decision_history if saved_id != doc_id
            ]
            if self._reviewing_flagged:
                status = "Span edited — choose Accept, Reject, or Ignore before clearing Flag."
            else:
                status = "Span edited — previous decision cleared."

        try:
            self._append_state(doc_id, state)
        except Exception as exc:
            self._restore_current_annotation_state(
                status=f"Could not save span edit: {exc}",
            )
            return

        self._state[doc_id] = state
        self._decision_history = decision_history
        self._loading = True
        try:
            self._set_widget_annotation_state(state, status=status)
        finally:
            self._loading = False

        warning = self._checkpoint_warning_if_large()
        if warning is not None:
            self.widget.status = warning

    def _on_flagged(self, change: Mapping[str, Any]) -> None:
        if self._loading or self._closed:
            return

        previous_state = self._state[self.current_id]
        try:
            self.flag(bool(change["new"]))
        except Exception as exc:
            self._loading = True
            try:
                self.widget.flagged = previous_state.flagged
                self._sync_summary_traits()
                self.widget.status = f"Could not save Flag change: {exc}"
            finally:
                self._loading = False

    def _on_event(self, change: Mapping[str, Any]) -> None:
        if self._loading or self._closed:
            return

        event = change["new"] or {}
        kind = event.get("type")

        try:
            if kind == "decision":
                self.decide(str(event.get("answer") or ""))
            elif kind == "undo_decision":
                self.undo_decision()
            elif kind == "review_flagged":
                self._start_flagged_review()
        except Exception as exc:
            self.widget.status = f"Could not apply action: {exc}"

    def _append_state(self, document_id: str, state: DocumentState) -> None:
        self._check_source_unchanged()
        self._check_output_unchanged()

        base = self._output_fingerprint
        if base is None:
            raise RuntimeError("No JSONL checkpoint is available for autosave")

        self._autosave.append(
            base=base,
            document_id=document_id,
            annotation=self._annotation_for_state(state),
        )

    def _checkpoint(self) -> Path:
        self._check_source_unchanged()
        self._check_output_unchanged()

        result, fingerprint = atomic_write_jsonl_with_fingerprint(
            self.output_path,
            self._iter_records(),
        )

        if self._source_is_output:
            if not isinstance(self._source, JsonlDocumentSource):
                raise RuntimeError("Only a JSONL source can be its own output")
            self._source.refresh()

        self._set_output_identity(fingerprint)
        self._autosave.discard()
        return result

    def _checkpoint_warning_if_large(self) -> str | None:
        if self._autosave.size < AUTOSAVE_CHECKPOINT_BYTES:
            return None

        try:
            self._checkpoint()
        except Exception as exc:
            return f"Autosaved, but JSONL checkpoint failed: {exc}"
        return None

    def _checkpoint_with_status(self, status: str) -> None:
        try:
            self._checkpoint()
        except Exception as exc:
            self.widget.status = (
                f"{status} Autosaved, but JSONL checkpoint failed: {exc}"
            )
        else:
            self.widget.status = status

    def _check_source_unchanged(self) -> None:
        if isinstance(self._source, JsonlDocumentSource):
            self._source.check_unchanged()

    def _check_output_unchanged(self) -> None:
        if self._output_signature is None:
            return

        stat = self.output_path.stat()
        current = stat.st_size, stat.st_mtime_ns
        if current != self._output_signature:
            raise RuntimeError(
                f"JSONL output {self.output_path} changed while the session was open"
            )

    def _set_output_identity(self, fingerprint: FileFingerprint) -> None:
        stat = self.output_path.stat()
        self._output_fingerprint = fingerprint
        self._output_signature = stat.st_size, stat.st_mtime_ns

    def _annotation_for_state(self, state: DocumentState) -> dict[str, Any]:
        return {
            "spans": (
                [annotation_span_to_dict(span) for span in state.spans]
                if state.materialized
                else None
            ),
            "answer": state.answer or None,
            "flagged": state.flagged,
        }

    def _iter_records(self) -> Iterator[dict[str, Any]]:
        for index, document_id in enumerate(self._source.ids):
            record = dict(self._source.record(index))
            record["annotation"] = self._annotation_for_state(self._state[document_id])
            yield record

    def _release_lock(self) -> None:
        if self._closed:
            return
        self._output_lock.release()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("This spanmark session is closed")
