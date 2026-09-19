# Legatus requests — Servo engine line (`legatus` branch)

Source: `legatus-mod/.claude/worktrees/bash-write-gate/docs/servo-fork-requests.md`
(measured Servo 0.5 vs Edge, 2026-09-19; read-only, owned by Legatus side).
Product: Legatus terminal pane renders its dashboard with this fork.

Repro page + probe commands: see source doc (`servo-gaps.html`).

| # | Request | Status | WPT before | WPT after | Commit |
|---|---------|--------|------------|-----------|--------|
| 1 | Range geometry: 1-char text range returns 4 rects, first ~580px wide at wrong top (want 1 glyph box, Edge: 46,14,7,16) | done | servo-gaps repro: 2 boxes incl. 780px line box | 1 box [45.8,14.2,7.0,16.1]; word/collapsed/end-caret/full-line exact; multi-node ends clip. Amendments: element starts not prepended (no whole container box); RTL same-node returns empty (no trustworthy geometry); regression test mozilla/range-text-rects.html (3/3 pass live). Open: (a) WPT css/cssom-view range files still FAIL (nested-text 8/5 vs 6/4: dup element+text box + abspos empty-counting need Chrome ground truth); (b) RTL/vertical/bidi limitation explicit: RTL same-node returns whole line boxes (3899e9dc; empty lists broke caret/highlight), no regress vs legacy; (c) multi-node middles keep legacy element boxes | 8804f281 + 8253e086 + ac4d7681 + 3899e9dc |
| 2 | Caret from point: `caretPositionFromPoint` + `caretRangeFromPoint` + `Selection.modify` all undefined | done | all undefined; WPT selection/modify*.html + idlharness entries failing | caret APIs return (#text,7), null outside; transformed offsets verified (collapsed ws offset 5, ß→SS offset 1); empty div/img report (el,0); modify character/word incl. <br> jumps, SyntaxError/NotSupportedError/TypeError paths; mozilla regression tests 3/3 + 9/9 live. Open: line/lineboundary/sentence/paragraph granularities (need layout line geometry), padding-of-nonempty elements | e6bdc780 + 469e94f0 + d9617681 |
| 6 | HIGH: `elementFromPoint` hits elements inside `[hidden]` (display:none) subtrees in long-lived DOM-morphed documents (fresh page OK). Breaks live pane clicks. Repro: toggle `hidden` on sibling sections + mutate children, then elementFromPoint over a visible element. BLOCKED 2026-09-19: 7 probe variants pass on dddcdade (batched writes, remove/re-insert, innerHTML-swap, 124 timed morphs, normal-flow shift, scrolled, scrolled+fixed overlay) — all return target + correct rect. Audit: damage bits nest (Relayout⊃SCT⊃Repaint) so paint/query trees can't diverge via flags; 0x0 fallback lives in process_box_area_request when root_transform_for_fragments fails. Needs exact live-pane DOM/churn pattern to reproduce | todo | 7/7 probe variants pass (no repro) | | |
| 3 | `document.execCommand` missing on Servo 0.5 (insertText/selectAll/copy) — verify vs our line (execCommand pref already on; insertText/bold probed working) | todo | | | |
| 4 | `var()` unresolved in SVG presentation attributes (`stroke="var(--c)"` → none; currentColor + class rules OK) | todo | | | |
| 5 | Emoji without colour font fallback draws empty box (low priority) | todo | | | |
| 7 | LOW (after #5): `text-overflow: ellipsis` not rendered (clips without drawing '…'). WPT: css/css-overflow/text-overflow-* | todo | | | |
| 8 | HIGH: mouse text selection (double-click selects word, drag extends, selection painted). Deps #1+#2 done (dom_position + modify). Mousedown-collapse + drag-extend + selection paint pre-existed; dblclick did nothing | done | no native dblclick selection (synthetic dblclick leaves selection empty) | native dblclick selects word; contract test mouse-selection-word.html 2/2 groups green via probe; word_around 19/19 vs ICU in scratch harness; #1/#2 spot probes unchanged | e3d41989 |

Out of scope (Legatus side): range-input dragging polyfill, embedder hooks
(navigation allowlist, downloads, permissions, file chooser).

## Log
- 2026-09-19: tracker created; order/scope corrected per Vitruvius (var() only, not currentColor/class; range = 4 rects not ~45). Starting #1.
- 2026-09-19: #1 done (8804f281). New TextRectsQuery: fragment-tree walk + OffsetMap + glyph-advance clipping + same-line merge + caret rects.
