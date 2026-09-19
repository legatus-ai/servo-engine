# Legatus requests — Servo engine line (`legatus` branch)

Source: `legatus-mod/.claude/worktrees/bash-write-gate/docs/servo-fork-requests.md`
(measured Servo 0.5 vs Edge, 2026-09-19; read-only, owned by Legatus side).
Product: Legatus terminal pane renders its dashboard with this fork.

Repro page + probe commands: see source doc (`servo-gaps.html`).

| # | Request | Status | WPT before | WPT after | Commit |
|---|---------|--------|------------|-----------|--------|
| 1 | Range geometry: 1-char text range returns 4 rects, first ~580px wide at wrong top (want 1 glyph box, Edge: 46,14,7,16) | doing | | | |
| 2 | Caret from point: `caretPositionFromPoint` + `caretRangeFromPoint` + `Selection.modify` all undefined | todo | | | |
| 3 | `document.execCommand` missing on Servo 0.5 (insertText/selectAll/copy) — verify vs our line (execCommand pref already on; insertText/bold probed working) | todo | | | |
| 4 | `var()` unresolved in SVG presentation attributes (`stroke="var(--c)"` → none; currentColor + class rules OK) | todo | | | |
| 5 | Emoji without colour font fallback draws empty box (low priority) | todo | | | |

Out of scope (Legatus side): range-input dragging polyfill, embedder hooks
(navigation allowlist, downloads, permissions, file chooser).

## Log
- 2026-09-19: tracker created; order/scope corrected per Vitruvius (var() only, not currentColor/class; range = 4 rects not ~45). Starting #1.
