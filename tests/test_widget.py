"""Tests for the thin anywidget bridge and bundled frontend."""

from typing import cast

import pytest

from spanmark._widget import SpanmarkWidget


def test_widget_defaults_and_frontend_are_wired() -> None:
    widget = SpanmarkWidget()

    assert widget.text == ""
    assert widget.labels == []
    assert widget.spans == []
    assert widget.answer == ""
    assert widget.flagged is False
    assert widget.allow_overlaps is False
    assert widget.can_undo is False
    assert widget.complete is False


def test_widget_traits_are_synced() -> None:
    widget = SpanmarkWidget()

    for name in (
        "text",
        "labels",
        "spans",
        "doc_id",
        "index",
        "total",
        "answer",
        "flagged",
        "allow_overlaps",
        "can_undo",
        "complete",
        "decided_count",
        "accept_count",
        "reject_count",
        "ignore_count",
        "flagged_count",
        "reviewing_flagged",
        "trim_whitespace",
        "event",
        "status",
    ):
        assert widget.traits()[name].metadata["sync"] is True


@pytest.mark.parametrize(
    ("text", "target", "expected_start", "expected_end"),
    [
        ("😀 firetrucks", "firetrucks", 2, 12),
        ("👩‍🚒 firemen drive firetrucks at work", "firetrucks", 18, 28),
        ("👩🏽‍🚒 firemen drive firetrucks at work", "firetrucks", 19, 29),
        ("A😀B café 東京 firetrucks", "firetrucks", 12, 22),
    ],
)
def test_offsets_are_python_unicode_code_points(
    text: str,
    target: str,
    expected_start: int,
    expected_end: int,
) -> None:
    start = text.index(target)
    end = start + len(target)

    assert (start, end) == (expected_start, expected_end)
    assert text[start:end] == target

    # JavaScript's native string offsets are UTF-16 code units. These examples
    # deliberately contain non-BMP characters before the target, so a JS-native
    # offset would differ from the persisted Python code-point offset.
    utf16_start = len(text[:start].encode("utf-16-le")) // 2
    assert utf16_start != start


def test_frontend_explicitly_converts_between_code_points_and_utf16() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    assert "return Array.from(text);" in esm
    assert "function buildCodePointToCodeUnitMap(text)" in esm
    assert "const cpToCu = buildCodePointToCodeUnitMap(text);" in esm
    assert "return codePoints(fragment.textContent).length;" in esm


def test_frontend_uses_only_suggestion_and_user_sources() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    assert 'span.source === "suggestion"' in esm
    assert 'source: "user"' in esm
    assert 'source: "human"' not in esm
    assert 'source: "edited"' not in esm


def test_frontend_uses_fixed_scrollable_document_viewport() -> None:
    widget = SpanmarkWidget()
    css = cast(str, widget._css)
    esm = cast(str, widget._esm)

    assert "height: 400px;" in css
    assert "overflow-y: auto;" in css
    assert "overflow-x: hidden;" in css
    assert "color-scheme: light;" in css
    assert "background: var(--so-surface);" in css
    assert "color: var(--so-text);" in css
    assert "--jp-" not in css
    assert "--colab-" not in css
    assert "textBox.scrollTop = 0;" in esm
    assert "rect.bottom - box.top + textBox.scrollTop" in esm


def test_frontend_resets_document_local_edit_state() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    assert 'model.on("change:doc_id", () => {' in esm
    assert "history = [];" in esm
    assert "selectedSpanId = null;" in esm
    assert "textBox.scrollTop = 0;" in esm


def test_frontend_cancels_pending_rail_render_frames() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    assert "let railFrame = null;" in esm
    assert "function cancelRailFrame()" in esm
    assert "cancelAnimationFrame(railFrame);" in esm
    assert "railFrame = requestAnimationFrame(() => {" in esm
    assert "railFrame = null;" in esm


def test_frontend_keeps_button_activation_and_shortcuts_distinct() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    button_activation_guard = (
        'tag === "button" && (event.code === "Space" || event.key === "Enter")'
    )
    assert button_activation_guard in esm
    assert esm.count("el.focus({ preventScroll: true });") >= 2


def test_frontend_uses_accessible_label_colors_without_duplicate_legend() -> None:
    widget = SpanmarkWidget()
    css = cast(str, widget._css)
    esm = cast(str, widget._esm)

    for color in (
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#0072B2",
        "#D55E00",
        "#CC79A7",
        "#000000",
    ):
        assert color in esm

    assert "Okabe-Ito color-universal palette" in esm
    assert "function contrastTextForColor(color)" in esm
    assert '"--so-label-foreground"' in esm
    assert "color: var(--so-label-foreground, white);" in css
    assert "so-legend" not in esm
    assert "so-legend" not in css


def test_frontend_inline_span_labels_stay_in_normal_text_flow() -> None:
    widget = SpanmarkWidget()
    css = cast(str, widget._css)
    esm = cast(str, widget._esm)

    span_start = css.index(".so-textlayer mark.so-inline-span {")
    span_end = css.index(".so-textlayer mark.so-inline-span.so-model {", span_start)
    span_css = css[span_start:span_end]

    assert "padding: 0 3px;" in span_css
    assert "line-height: 1.3;" in span_css
    assert "box-decoration-break: clone;" in span_css
    assert "-webkit-box-decoration-break: clone;" in span_css

    model_start = span_end
    model_end = css.index(
        ".so-textlayer mark.so-inline-span.so-selected {", model_start
    )
    model_css = css[model_start:model_end]
    assert "border-style: dashed;" in model_css

    start = css.index(".so-inline-label {")
    end = css.index(".so-rail-seg,", start)
    label_css = css[start:end]

    assert "display: inline-block;" in label_css
    assert "font-size: 0.6em;" in label_css
    assert "color: var(--so-muted-text);" in label_css
    assert "vertical-align: baseline;" in label_css
    assert "white-space: nowrap;" in label_css
    assert "border:" not in label_css
    assert "background:" not in label_css
    assert "padding:" not in label_css
    assert "vertical-align: super;" not in css
    assert "so-inline-model-dot" not in css
    assert "so-inline-model-dot" not in esm
    assert "◆" not in esm
    assert "badge.textContent = span.label;" in esm

    span_text = esm.index('document.createTextNode(chars.slice(start, end).join(""))')
    inline_label = esm.index('label.className = "so-inline-label"', span_text)
    mark_append = esm.index("mark.appendChild(label);", inline_label)
    assert span_text < inline_label < mark_append


def test_frontend_exposes_flagged_review_controls() -> None:
    widget = SpanmarkWidget()
    esm = cast(str, widget._esm)
    css = cast(str, widget._css)

    assert widget.reviewing_flagged is False
    assert "`Review flagged (${flagged})`" in esm
    assert 'emit("review_flagged")' in esm
    assert 'model.get("complete") && !model.get("reviewing_flagged")' in esm
    assert 'model.on("change:reviewing_flagged", () => {' in esm
    assert 'if (!model.get("reviewing_flagged")) {' in esm
    assert ".so-completion-actions" in css


def test_completion_screen_disables_annotation_shortcuts_but_keeps_undo() -> None:
    esm = cast(str, SpanmarkWidget()._esm)

    completion_guard = esm.index("if (completionVisible) {")
    shortcut_handler = esm.index(
        "if (!event.ctrlKey && !event.metaKey && !event.altKey) {",
        completion_guard,
    )
    guard = esm[completion_guard:shortcut_handler]

    assert 'event.key === "Backspace"' in guard
    assert 'emit("undo_decision")' in guard
    assert "return;" in guard
