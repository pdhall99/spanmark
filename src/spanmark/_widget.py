"""The thin anywidget bridge between Python state and the browser UI."""

from pathlib import Path

import anywidget
import traitlets

_STATIC = Path(__file__).parent / "static"


class SpanmarkWidget(anywidget.AnyWidget):
    """Private browser widget used by `AnnotationSession`."""

    _esm = _STATIC / "widget.js"
    _css = _STATIC / "widget.css"

    text = traitlets.Unicode("").tag(sync=True)
    labels = traitlets.List(traitlets.Unicode(), default_value=[]).tag(sync=True)
    spans = traitlets.List(traitlets.Dict(), default_value=[]).tag(sync=True)

    doc_id = traitlets.Unicode("").tag(sync=True)
    index = traitlets.Int(0).tag(sync=True)
    total = traitlets.Int(0).tag(sync=True)

    answer = traitlets.Unicode("").tag(sync=True)
    flagged = traitlets.Bool(False).tag(sync=True)
    allow_overlaps = traitlets.Bool(False).tag(sync=True)
    can_undo = traitlets.Bool(False).tag(sync=True)
    complete = traitlets.Bool(False).tag(sync=True)
    reviewing_flagged = traitlets.Bool(False).tag(sync=True)

    decided_count = traitlets.Int(0).tag(sync=True)
    accept_count = traitlets.Int(0).tag(sync=True)
    reject_count = traitlets.Int(0).tag(sync=True)
    ignore_count = traitlets.Int(0).tag(sync=True)
    flagged_count = traitlets.Int(0).tag(sync=True)

    trim_whitespace = traitlets.Bool(True).tag(sync=True)

    event = traitlets.Dict().tag(sync=True)
    status = traitlets.Unicode("").tag(sync=True)
