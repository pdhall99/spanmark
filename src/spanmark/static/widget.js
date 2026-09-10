function render({ model, el }) {
    let selectedLabel = model.get("labels")[0] || null;
    let selectedSpanId = null;
    let history = [];
    let railFrame = null;

    // Okabe-Ito color-universal palette. Color is always paired with label text,
    // so it remains a redundant cue rather than the only way to identify a label.
    const PALETTE = [
        "#E69F00", "#56B4E9", "#009E73", "#F0E442",
        "#0072B2", "#D55E00", "#CC79A7", "#000000"
    ];

    function colorForLabel(label) {
        const labels = model.get("labels");
        const index = Math.max(0, labels.indexOf(label));
        return PALETTE[index % PALETTE.length];
    }

    function contrastTextForColor(color) {
        const channel = value => {
            const srgb = value / 255;
            return srgb <= 0.04045
                ? srgb / 12.92
                : Math.pow((srgb + 0.055) / 1.055, 2.4);
        };

        const r = channel(Number.parseInt(color.slice(1, 3), 16));
        const g = channel(Number.parseInt(color.slice(3, 5), 16));
        const b = channel(Number.parseInt(color.slice(5, 7), 16));
        const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        const whiteContrast = 1.05 / (luminance + 0.05);
        const blackContrast = (luminance + 0.05) / 0.05;
        return whiteContrast >= blackContrast ? "#ffffff" : "#000000";
    }

    el.innerHTML = "";
    el.classList.add("so-root");
    el.tabIndex = 0;

    const head = document.createElement("div");
    head.className = "so-head";
    const doc = document.createElement("div");
    doc.className = "so-doc";
    const progress = document.createElement("div");
    progress.className = "so-progress";
    head.append(doc, progress);

    const labelbar = document.createElement("div");
    labelbar.className = "so-labelbar";

    const textBox = document.createElement("div");
    textBox.className = "so-text";

    const textLayer = document.createElement("div");
    textLayer.className = "so-textlayer";

    const railLayer = document.createElement("div");
    railLayer.className = "so-rail-layer";

    textBox.append(textLayer, railLayer);

    const actions = document.createElement("div");
    actions.className = "so-actions";

    const completion = document.createElement("div");
    completion.className = "so-completion";

    const help = document.createElement("div");
    help.className = "so-help";
    help.innerHTML =
        'Select text to add a span. Click an annotation to select it; ' +
        'double-click to remove it. ' +
        '<span class="so-key">A</span> accept, ' +
        '<span class="so-key">X</span> reject, ' +
        '<span class="so-key">Space</span> ignore, ' +
        '<span class="so-key">F</span> flag, ' +
        '<span class="so-key">Backspace / Mac Delete</span> undo previous decision, ' +
        '<span class="so-key">1–9</span> choose/relabel, ' +
        '<span class="so-key">Del / Mac Fn+Delete</span> remove selected span, ' +
        '<span class="so-key">Ctrl/Cmd+Z</span> undo span edit, ' +
        '<span class="so-key">Esc</span> clear span selection.';

    const status = document.createElement("div");
    status.className = "so-status";

    el.append(head, labelbar, textBox, actions, completion, help, status);

    function emit(type, extra = {}) {
        model.set("event", {
            type,
            nonce: Date.now() + Math.random(),
            ...extra,
        });
        model.save_changes();
    }

    function makeButton(label, onclick, className = "") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        if (className) button.className = className;
        button.addEventListener("click", () => {
            onclick();
            el.focus({ preventScroll: true });
        });
        return button;
    }

    function cancelRailFrame() {
        if (railFrame !== null) {
            cancelAnimationFrame(railFrame);
            railFrame = null;
        }
    }

    function spanId(span, index) {
        return String(span._id ?? `${span.start}:${span.end}:${span.label}:${index}`);
    }

    function pushHistory() {
        history.push(JSON.parse(JSON.stringify(model.get("spans"))));
        if (history.length > 100) history.shift();
    }

    function setSpans(spans) {
        model.set("spans", spans);
        model.set("status", "");
        model.save_changes();
    }

    function undoEdit() {
        if (!history.length) {
            model.set("status", "Nothing to undo.");
            model.save_changes();
            return;
        }
        selectedSpanId = null;
        setSpans(history.pop());
    }

    function codePoints(text) {
        return Array.from(text);
    }

    function buildCodePointToCodeUnitMap(text) {
        const cps = codePoints(text);
        const map = [0];
        let cu = 0;
        for (const cp of cps) {
            cu += cp.length;
            map.push(cu);
        }
        return map;
    }

    function characterOffset(root, node, offset) {
        const range = document.createRange();
        range.selectNodeContents(root);
        range.setEnd(node, offset);

        const fragment = range.cloneContents();
        fragment.querySelectorAll?.(".so-inline-label").forEach(x => x.remove());

        return codePoints(fragment.textContent).length;
    }

    function renderHead() {
        const i = model.get("index") + 1;
        const total = model.get("total");
        const decided = model.get("decided_count");
        const flagged = model.get("flagged_count");
        doc.textContent = `Document: ${model.get("doc_id")}`;
        progress.textContent = model.get("reviewing_flagged")
            ? `Flagged review  •  ${flagged} remaining`
            : `${i} / ${total}  •  ${decided} decided  •  ${flagged} flagged`;
    }

    function relabelSelected(label) {
        if (selectedSpanId === null) return false;

        const spans = [...model.get("spans")];
        const i = spans.findIndex((s, idx) => spanId(s, idx) === selectedSpanId);
        if (i < 0) {
            selectedSpanId = null;
            return false;
        }

        pushHistory();
        const updated = {
            ...spans[i],
            label,
            source: "user",
        };
        delete updated.score;
        spans[i] = updated;
        setSpans(spans);
        return true;
    }

    function chooseLabel(label) {
        selectedLabel = label;
        relabelSelected(label);
        renderLabels();
    }

    function renderLabels() {
        labelbar.innerHTML = "";
        const labels = model.get("labels");

        if (!labels.includes(selectedLabel)) {
            selectedLabel = labels[0] || null;
        }

        labels.forEach((label, i) => {
            const button = makeButton(`${i + 1}: ${label}`, () => chooseLabel(label));
            const color = colorForLabel(label);
            button.classList.add("so-label-button");
            button.style.setProperty("--so-label-color", color);
            button.style.setProperty(
                "--so-label-foreground",
                contrastTextForColor(color)
            );
            if (label === selectedLabel) button.classList.add("active");
            labelbar.appendChild(button);
        });

        labelbar.appendChild(
            makeButton("Clear spans", () => {
                if (!model.get("spans").length) return;
                if (!window.confirm("Remove all spans from this document?")) return;
                pushHistory();
                selectedSpanId = null;
                setSpans([]);
            })
        );
    }

    function syncSelectedOverlay() {
        railLayer.querySelectorAll("[data-span-id]").forEach(node => {
            node.classList.toggle(
                "so-selected",
                node.dataset.spanId === selectedSpanId
            );
        });
        textLayer.querySelectorAll("mark[data-span-id]").forEach(node => {
            node.classList.toggle(
                "so-selected",
                node.dataset.spanId === selectedSpanId
            );
        });
    }

    function assignRailLanes(spans) {
        const laneEnds = [];
        const laneById = {};

        for (const span of spans) {
            let lane = 0;
            while (
                lane < laneEnds.length &&
                laneEnds[lane] > Number(span.start)
            ) {
                lane += 1;
            }
            laneEnds[lane] = Number(span.end);
            laneById[spanId(span, span.__renderIndex)] = lane;
        }

        return laneById;
    }

    function renderRails() {
        cancelRailFrame();
        railLayer.innerHTML = "";

        const text = model.get("text");
        const spans = [...model.get("spans")]
            .map((s, i) => ({ ...s, __renderIndex: i }))
            .sort((a, b) =>
                a.start - b.start ||
                b.end - a.end ||
                String(a.label).localeCompare(String(b.label))
            );

        const laneById = assignRailLanes(spans);
        const laneValues = Object.values(laneById);
        const maxLane = laneValues.length ? Math.max(...laneValues) : -1;

        const laneStep = 22;
        const extra = maxLane >= 0 ? (maxLane + 1) * laneStep + 3 : 0;
        textBox.style.setProperty("--so-rail-extra", `${extra}px`);

        railFrame = requestAnimationFrame(() => {
            railFrame = null;
            railLayer.innerHTML = "";
            if (!textLayer.firstChild || !spans.length) return;

            const cpToCu = buildCodePointToCodeUnitMap(text);
            const textNode = textLayer.firstChild;
            const box = textBox.getBoundingClientRect();
            const railOffset = 3;

            function selectSpanFromEvent(sid, span) {
                selectedSpanId = selectedSpanId === sid ? null : sid;
                if (selectedSpanId !== null) {
                    selectedLabel = span.label;
                }
                renderLabels();
                syncSelectedOverlay();
            }

            function removeSpanById(sid) {
                pushHistory();
                const current = model.get("spans");
                const filtered = current.filter(
                    (s, idx) => spanId(s, idx) !== sid
                );
                selectedSpanId = null;
                setSpans(filtered);
                window.getSelection()?.removeAllRanges();
            }

            for (const span of spans) {
                const sid = spanId(span, span.__renderIndex);
                const lane = laneById[sid];
                const color = colorForLabel(span.label);

                const startCp = Math.max(
                    0, Math.min(cpToCu.length - 1, Number(span.start))
                );
                const endCp = Math.max(
                    0, Math.min(cpToCu.length - 1, Number(span.end))
                );

                const range = document.createRange();
                range.setStart(textNode, cpToCu[startCp]);
                range.setEnd(textNode, cpToCu[endCp]);

                const rects = Array.from(range.getClientRects())
                    .filter(rect => rect.width > 0);
                if (!rects.length) continue;

                const railYFor = rect =>
                    rect.bottom - box.top + textBox.scrollTop +
                    railOffset + lane * laneStep;

                rects.forEach(rect => {
                    const seg = document.createElement("div");
                    seg.className = "so-rail-seg";
                    if (span.source === "suggestion") seg.classList.add("so-model");
                    if (sid === selectedSpanId) seg.classList.add("so-selected");
                    seg.dataset.spanId = sid;
                    seg.style.setProperty("--so-span-color", color);
                    seg.style.left = `${rect.left - box.left}px`;
                    seg.style.width = `${rect.width}px`;
                    seg.style.top = `${railYFor(rect)}px`;
                    seg.title = `${span.label} (${span.start}, ${span.end})`;
                    seg.addEventListener("click", event => {
                        event.stopPropagation();
                        selectSpanFromEvent(sid, span);
                    });
                    seg.addEventListener("dblclick", event => {
                        event.preventDefault();
                        event.stopPropagation();
                        removeSpanById(sid);
                    });
                    railLayer.appendChild(seg);
                });

                const firstRect = rects[0];
                const badge = document.createElement("div");
                badge.className = "so-rail-badge";
                if (span.source === "suggestion") badge.classList.add("so-model");
                if (sid === selectedSpanId) badge.classList.add("so-selected");
                badge.dataset.spanId = sid;
                badge.style.setProperty("--so-span-color", color);
                badge.textContent = span.label;
                badge.style.left = `${firstRect.left - box.left}px`;
                badge.style.top = `${railYFor(firstRect) + 5}px`;
                badge.title = `${span.label} (${span.start}, ${span.end})`;
                badge.addEventListener("click", event => {
                    event.stopPropagation();
                    selectSpanFromEvent(sid, span);
                });
                badge.addEventListener("dblclick", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    removeSpanById(sid);
                });
                railLayer.appendChild(badge);
            }
        });
    }

    function renderInlineText() {
        cancelRailFrame();
        railLayer.innerHTML = "";
        textBox.style.setProperty("--so-rail-extra", "0px");

        const text = model.get("text") || "";
        const chars = codePoints(text);
        const textLength = chars.length;
        const spans = [...model.get("spans")]
            .map((s, i) => ({ ...s, __renderIndex: i }))
            .sort((a, b) => a.start - b.start || a.end - b.end);

        textLayer.innerHTML = "";
        let pos = 0;

        for (const span of spans) {
            const start = Math.max(0, Math.min(textLength, Number(span.start)));
            const end = Math.max(start, Math.min(textLength, Number(span.end)));

            if (start > pos) {
                textLayer.appendChild(
                    document.createTextNode(chars.slice(pos, start).join(""))
                );
            }

            if (start < pos) continue;

            const mark = document.createElement("mark");
            mark.className = "so-inline-span";
            const sid = spanId(span, span.__renderIndex);
            mark.dataset.spanId = sid;
            mark.style.setProperty("--so-span-color", colorForLabel(span.label));

            if (span.source === "suggestion") {
                mark.classList.add("so-model");
                const scoreText = typeof span.score === "number"
                    ? ` (${span.score.toFixed(3)})`
                    : "";
                mark.title =
                    `Model suggestion${scoreText}. Click to select; double-click to remove.`;
            } else {
                mark.title = "Click to select; double-click to remove.";
            }

            if (sid === selectedSpanId) {
                mark.classList.add("so-selected");
            }

            mark.appendChild(
                document.createTextNode(chars.slice(start, end).join(""))
            );

            const label = document.createElement("span");
            label.className = "so-inline-label";
            label.textContent = span.label;
            mark.appendChild(label);

            mark.addEventListener("click", event => {
                event.stopPropagation();
                selectedSpanId = selectedSpanId === sid ? null : sid;
                if (selectedSpanId !== null) {
                    selectedLabel = span.label;
                }
                renderLabels();
                syncSelectedOverlay();
            });

            mark.addEventListener("dblclick", event => {
                event.preventDefault();
                event.stopPropagation();
                pushHistory();
                const current = model.get("spans");
                const filtered = current.filter(
                    (s, idx) => spanId(s, idx) !== sid
                );
                selectedSpanId = null;
                setSpans(filtered);
                window.getSelection()?.removeAllRanges();
            });

            textLayer.appendChild(mark);
            pos = end;
        }

        if (pos < textLength) {
            textLayer.appendChild(
                document.createTextNode(chars.slice(pos).join(""))
            );
        }
    }

    function renderText() {
        if (model.get("allow_overlaps")) {
            textLayer.textContent = model.get("text") || "";
            renderRails();
        } else {
            renderInlineText();
        }
    }

    function deleteSelectedSpan() {
        if (selectedSpanId === null) {
            model.set("status", "Select a span first.");
            model.save_changes();
            return false;
        }

        const current = model.get("spans");
        const filtered = current.filter(
            (s, idx) => spanId(s, idx) !== selectedSpanId
        );

        if (filtered.length === current.length) {
            selectedSpanId = null;
            model.set("status", "Selected span was not found.");
            model.save_changes();
            return false;
        }

        pushHistory();
        selectedSpanId = null;
        setSpans(filtered);
        window.getSelection()?.removeAllRanges();
        return true;
    }

    function renderActions() {
        actions.innerHTML = "";
        const answer = model.get("answer");

        for (const [value, label] of [
            ["accept", "✓ Accept"],
            ["reject", "✕ Reject"],
            ["ignore", "– Ignore"],
        ]) {
            const button = makeButton(label, () => emit("decision", { answer: value }));
            button.dataset.action = value;
            if (answer === value) button.classList.add("active");
            actions.appendChild(button);
        }

        const flag = makeButton(
            "⚑ Flag",
            () => {
                model.set("flagged", !model.get("flagged"));
                model.save_changes();
            }
        );
        flag.dataset.action = "flag";
        if (model.get("flagged")) flag.classList.add("active");
        actions.appendChild(flag);

        if (!model.get("reviewing_flagged")) {
            const undo = makeButton("↶ Undo", () => emit("undo_decision"));
            undo.dataset.action = "undo";
            undo.disabled = !model.get("can_undo");
            undo.title = model.get("can_undo")
                ? "Undo the previous submitted decision"
                : "No previous submitted decision to undo";
            actions.appendChild(undo);
        }
    }

    function renderCompletion() {
        const showCompletion =
            model.get("complete") && !model.get("reviewing_flagged");

        labelbar.style.display = showCompletion ? "none" : "";
        textBox.style.display = showCompletion ? "none" : "";
        actions.style.display = showCompletion ? "none" : "";
        help.style.display = showCompletion ? "none" : "";
        completion.classList.toggle("show", showCompletion);

        if (!showCompletion) {
            completion.innerHTML = "";
            return;
        }

        completion.innerHTML = "";

        const title = document.createElement("div");
        title.className = "so-completion-title";
        title.textContent = "✓ Annotation complete";

        const subtitle = document.createElement("div");
        subtitle.textContent =
            `${model.get("decided_count")} / ${model.get("total")} examples decided`;

        const counts = document.createElement("div");
        counts.className = "so-completion-counts";

        for (const [label, value] of [
            ["Accept", model.get("accept_count")],
            ["Reject", model.get("reject_count")],
            ["Ignore", model.get("ignore_count")],
            ["Flagged", model.get("flagged_count")],
        ]) {
            const item = document.createElement("span");
            item.className = "so-completion-count";
            item.textContent = `${label}: ${value}`;
            counts.appendChild(item);
        }

        const completionActions = document.createElement("div");
        completionActions.className = "so-completion-actions";

        const flagged = model.get("flagged_count");
        if (flagged > 0) {
            const review = makeButton(
                `Review flagged (${flagged})`,
                () => emit("review_flagged")
            );
            completionActions.appendChild(review);
        }

        const undo = makeButton("↶ Undo last decision", () => emit("undo_decision"));
        undo.disabled = !model.get("can_undo");
        completionActions.appendChild(undo);

        completion.append(title, subtitle, counts, completionActions);
    }

    function renderStatus() {
        status.textContent = model.get("status") || "";
    }

    textBox.addEventListener("click", (event) => {
        if (event.target === textBox || event.target === textLayer) {
            selectedSpanId = null;
            syncSelectedOverlay();
        }
    });

    textLayer.addEventListener("mouseup", () => {
        if (!selectedLabel) return;

        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return;

        const range = selection.getRangeAt(0);
        if (
            !textLayer.contains(range.startContainer) ||
            !textLayer.contains(range.endContainer)
        ) return;

        let start = characterOffset(textLayer, range.startContainer, range.startOffset);
        let end = characterOffset(textLayer, range.endContainer, range.endOffset);
        if (end < start) [start, end] = [end, start];

        const chars = codePoints(model.get("text"));

        if (model.get("trim_whitespace")) {
            while (start < end && /\s/.test(chars[start])) start += 1;
            while (end > start && /\s/.test(chars[end - 1])) end -= 1;
        }

        if (start === end) {
            selection.removeAllRanges();
            return;
        }

        const spans = [...model.get("spans")];

        if (model.get("allow_overlaps")) {
            if (spans.some(s => (
                Number(s.start) === start &&
                Number(s.end) === end &&
                String(s.label) === String(selectedLabel)
            ))) {
                model.set("status", "That exact span already exists.");
                model.save_changes();
                selection.removeAllRanges();
                return;
            }
        } else {
            if (spans.some(s =>
                start < Number(s.end) && Number(s.start) < end
            )) {
                model.set("status", "That selection overlaps an existing span.");
                model.save_changes();
                selection.removeAllRanges();
                return;
            }
        }

        pushHistory();
        selectedSpanId = null;
        spans.push({
            start,
            end,
            label: selectedLabel,
            source: "user",
            _id: `user-${Date.now()}-${Math.random()}`,
        });
        setSpans(spans);
        selection.removeAllRanges();
    });

    function actionShortcut(event) {
        if (event.key.toLowerCase() === "a") {
            emit("decision", { answer: "accept" });
            return true;
        }
        if (event.key.toLowerCase() === "x") {
            emit("decision", { answer: "reject" });
            return true;
        }
        if (event.code === "Space") {
            emit("decision", { answer: "ignore" });
            return true;
        }
        if (event.key.toLowerCase() === "f") {
            model.set("flagged", !model.get("flagged"));
            model.save_changes();
            return true;
        }
        return false;
    }

    function onKeyDown(event) {
        if (!el.contains(document.activeElement)) return;

        const tag = document.activeElement?.tagName?.toLowerCase();
        if (
            tag === "input" ||
            tag === "textarea" ||
            document.activeElement?.isContentEditable
        ) return;

        if (tag === "button" && (event.code === "Space" || event.key === "Enter")) {
            return;
        }

        const completionVisible =
            model.get("complete") && !model.get("reviewing_flagged");
        if (completionVisible) {
            if (
                event.key === "Backspace" &&
                !event.ctrlKey && !event.metaKey && !event.altKey
            ) {
                event.preventDefault();
                emit("undo_decision");
            }
            return;
        }

        if (!event.ctrlKey && !event.metaKey && !event.altKey) {
            const n = Number(event.key);
            if (
                Number.isInteger(n) &&
                n >= 1 &&
                n <= model.get("labels").length
            ) {
                event.preventDefault();
                chooseLabel(model.get("labels")[n - 1]);
                return;
            }

            if (event.key === "Backspace") {
                event.preventDefault();
                if (!model.get("reviewing_flagged")) {
                    emit("undo_decision");
                }
                return;
            }

            if (actionShortcut(event)) {
                event.preventDefault();
                return;
            }
        }

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
            event.preventDefault();
            undoEdit();
            return;
        }

        if (
            (event.key === "Delete" || event.code === "Delete") &&
            !event.ctrlKey && !event.metaKey && !event.altKey
        ) {
            event.preventDefault();
            deleteSelectedSpan();
            return;
        }

        if (event.key === "Escape") {
            selectedSpanId = null;
            window.getSelection()?.removeAllRanges();
            syncSelectedOverlay();
        }
    }

    el.addEventListener("keydown", onKeyDown);

    model.on("change:spans", renderText);
    model.on("change:text", renderText);
    model.on("change:allow_overlaps", renderText);
    model.on("change:labels", () => {
        renderLabels();
        renderText();
    });
    model.on("change:answer", renderActions);
    model.on("change:flagged", renderActions);
    model.on("change:can_undo", () => {
        renderActions();
        renderCompletion();
    });
    model.on("change:complete", renderCompletion);
    model.on("change:reviewing_flagged", () => {
        renderHead();
        renderActions();
        renderCompletion();
    });
    model.on("change:accept_count", renderCompletion);
    model.on("change:reject_count", renderCompletion);
    model.on("change:ignore_count", renderCompletion);
    model.on("change:index", renderHead);
    model.on("change:total", renderHead);
    model.on("change:doc_id", () => {
        history = [];
        selectedSpanId = null;
        textBox.scrollTop = 0;
        window.getSelection()?.removeAllRanges();
        syncSelectedOverlay();
        renderHead();
    });
    model.on("change:decided_count", () => {
        renderHead();
        renderCompletion();
    });
    model.on("change:flagged_count", () => {
        renderHead();
        renderCompletion();
    });
    model.on("change:status", renderStatus);

    renderHead();
    renderLabels();
    renderText();
    renderActions();
    renderCompletion();
    renderStatus();

    el.addEventListener("mousedown", () => {
        if (!el.contains(document.activeElement)) el.focus({ preventScroll: true });
    });

    return () => {
        cancelRailFrame();
        el.removeEventListener("keydown", onKeyDown);
    };
}

export default { render };
