# Design note: `line-clamp` / `-webkit-line-clamp` layout + `block-ellipsis` (Row 14)

Status: DRAFT for Vitruvius review. No code until approved.

## Scope (baseline: scoreboard run 36280908230, 234/286 FAIL under `line-clamp/`)

In scope (229 FAIL):

| Family | FAIL/total | Needs |
|---|---|---|
| `line-clamp-NNN` core | 32/42 | count N non-phantom lines, drop the rest, ellipsis on line N |
| `webkit-line-clamp-*` | 33/57 | same via legacy path (Row 13 adjuster already blockifies display) |
| `line-clamp-auto-*` | 47/63 | `max-lines: auto` + max-height → line budget from block size |
| `block-ellipsis-*` | 50/51 | string markers, bidi, quirks, repaints |
| `line-clamp-with-abspos-*` + `with-fixed-pos-*` | 40/40 | abspos visibility rule (containing block vs clamp point) |
| `line-clamp-with-floats-*` | 10/10 | floats before the clamp point stay |
| `line-clamp-balance-*` | 11/12 | `text-wrap: balance` interplay (propose phase 2 — see open Q3) |
| `with-text-overflow-string-*` | 3/3 | `block-ellipsis` vs `text-overflow: <string>` precedence |
| `line-clamp-bfc`, `content-height-dynamic`, `block-in-inline` | 3/3 | BFC exclusion (already works), dynamic change, block-in-inline counting |

Out (Row 15): `continue-001`, `discard/*` (continue semantics, 5 files). Crash tests
already pass (no crash = pass). `.tentative` files stay tentative.

## Where clamping happens (all in `components/layout/flow/inline/`)

1. **Line counter** — new `lines_laid_out: u32` field on `InlineFormattingContextLayout`
   (`mod.rs:818`). Increment in `finish_current_line_and_reset` (`mod.rs:1104`) for
   non-phantom lines only (`is_phantom_line` is already computed there; phantom lines
   must not consume the budget).
2. **Clamp trigger** — read from `self.containing_block().style.get_box().line_clamp`
   (same style source the ellipsis gate uses at `mod.rs:1252`). Computed
   `LineClamp` offers `is_none()`, `max_lines` (`Optional` count + `Auto` kw),
   `block_ellipsis`, `webkit_legacy`. The `-webkit-line-clamp` shorthand already folds
   into `line_clamp` (Row 13), so one trigger covers both spellings.
3. **Last-line truncation** — generalize `ellipsis::truncate_line_for_ellipsis`
   (`ellipsis.rs:275`): marker = `block_ellipsis` (`Ellipsis` → existing U+2026 path;
   `String` → extend `shape_ellipsis` to shape an arbitrary string in the block font;
   `NoEllipsis` → truncate without marker). Visual-order walk already handles RTL.
4. **Dropping post-clamp content** — the breaker must stop pulling content after line N
   (open Q1). Floats before the clamp point survive naturally (top-level IFC fragments,
   not line content); abspos visibility needs positioning-context filtering by clamp
   point (open Q1b).
5. **Ellipsis fit** — `block-ellipsis-001` requires the marker after the last soft wrap
   opportunity that still fits: either reserve the ellipsis advance from
   `available_inline_size` (`mod.rs:1220-1239`) before breaking the last line, or
   re-break the last line post-pass (open Q2).

## WPT plan (all reftests — pixel comparison in the pane harness, post-resume)

Probe contracts first: clamped container height == N line-heights; `Range` rects of
line N+1 text resolve to nothing (content discarded, not merely clipped); full text
still in DOM/selection. Then the families above in scope order: core → legacy →
block-ellipsis → auto → floats/abspos → strings/bfc/dynamic → balance (if Q3 says in).

## Open questions for review

1. **Stop-the-breaker site**: where to discard post-clamp content without disturbing
   float placement and abspos hoisting? (1b: filter hoisted abspos by clamp point?)
2. **Ellipsis width**: pre-reserve from available inline size before breaking the last
   line, or post-pass re-break?
3. **Balance**: gate `line-clamp-balance-*` to phase 2 if `text-wrap: balance` itself
   is unsupported — check balance support before committing to all 11.
