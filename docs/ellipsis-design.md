# Design note: `text-overflow: ellipsis` (Legatus #7, phase 1)

Status: proposed, awaiting Vitruvius review. No code yet.

## Goal (phase 1)

Single-line ellipsis at the logical end of an overflowing line:
`text-overflow: ellipsis` (one value) on a block container. Two-value
syntax (`clip ellipsis`, physical sides), `<string>` values, and
multi-line clamping stay phase 2.

## Where truncation happens

A fragment post-pass inside inline layout, not line-box construction.

Rationale: line breaking must stay untouched. `white-space: nowrap`
already yields one overflowing line; with wrapping, unbreakable runs
also overflow. In both cases the line breaker has done its job and the
line's inline size is known (`LineUnderConstruction.inline_position`
vs the available size from `placement_state.containing_block.size.inline`,
float-adjusted as in `finish_current_line_and_reset`).

Concretely: in `InlineFormattingContextLayout::finish_current_line_and_reset`
(`components/layout/flow/inline/mod.rs`), after the overflow decision,
truncate the committed `Vec<LineItem>` **after** bidi visual reorder
(the reorder currently happens inside
`LineItemLayout::layout_line_items`, `line.rs`; truncation needs a hook
on the visual order, so the reorder moves earlier or the truncation
runs on the reordered items). Truncating visual order puts the ellipsis
at the correct visual end for LTR and RTL without special-casing
direction; `direction` only decides which visual end is the logical end
(LTR: right, RTL: left), and the single `ellipsis` value always means
the logical end (`TextOverflow.second` with `sides_are_logical`).

Why not during breaking: the breaker commits whole unbreakable segments
and has no per-glyph shrink step; retrofitting truncation there would
tangle breaking, justification, and float placement. A post-pass sees
final advances and only edits trailing items.

## Gate

Truncate a line only when all hold on the block container style:

- `text-overflow` second side (logical end) is `Ellipsis` (phase 1;
  `String(_)` and two-value physical sides are phase 2),
- the line's content inline size exceeds the available inline size
  (after float adjustment),
- the line is not a phantom line.

No `white-space` or `overflow` precondition beyond what the style
already requires: `overflow: hidden|clip` clips via existing clip nodes;
`overflow: visible|scroll` still shows the ellipsis (Chrome parity —
ellipsis renders whenever content overflows, clipping is orthogonal).
`white-space: nowrap` is the common case, not a gate: wrapped lines
with unbreakable overflow get the same treatment per spec.

## Truncation algorithm (visual order, from the visual end)

Line items hold shaped glyphs (`TextRunLineItem.text:
Vec<Arc<ShapedTextSlice>>` with `total_advance()`), so truncation is
glyph arithmetic, mirroring the existing `trim_whitespace_at_end`
pattern in `line.rs`:

1. Shape the ellipsis run once per distinct font (`Font::shape_text`
   on "\u{2026}" with the truncated run's `FontAndScriptInfo`), measure
   its advance E.
2. Walk trailing line items from the visual end, dropping whole items
   (atomic inlines, trailing padding/border/margin markers stay — only
   content items go) and then trailing shaped slices inside the last
   text item until the freed space fits E. If even the first item plus
   E overflows, the line shows only the ellipsis.
3. Shorten the last surviving text item in place (drain trailing
   slices) and append the ellipsis slices as a new trailing
   `LineItem::TextRun` (or extend the same item) with an **empty**
   `character_range_in_dom_node`, so no DOM text claims the ellipsis.

Inline boxes (spans): truncation crosses box boundaries freely — boxes
contribute no width themselves, only their text children do; the
ellipsis inherits the style/font of the truncated run it replaces.
Inline-blocks and other atomics at the visual end are dropped whole
(they cannot be partially shown); floats/abspos placeholders are
skipped, never truncated.

## Ellipsis glyph sourcing

- U+2026 shaped with the truncated run's font (`FontAndScriptInfo`).
- If the font lacks the glyph (shaper returns .notdef — detect via the
  shaped glyph id mapping to the missing-glyph sentinel, same check the
  text path uses for tofu avoidance), fall back to shaping "..."
  (three U+002E) with the same font.
- `<string>` values (`TextOverflowSide::String`) are phase 2.
- `direction: rtl` needs no extra work: truncation walks the visual
  order, and RTL lines are visually mirrored by the existing reorder,
  so the ellipsis lands at the visual left = logical end.

## Hit-testing and selection on truncated text

- Dropped tail glyphs keep their DOM nodes and offsets: fragments are
  shortened, not their `character_range_in_dom_node`, so
  `Range.getClientRects`/`getBoundingClientRect` still resolve (boxes
  report truncated geometry, matching Chrome).
- Caret mapping (`character_offset`, used by #2) clamps hidden offsets
  to the last visible glyph of the shortened fragment.
- Clicks landing on the ellipsis map to the truncation boundary offset
  (start of the hidden tail), so click-drag selection still covers the
  full text.
- `getSelection().toString()` and copy include the FULL text: the
  ellipsis fragment carries an empty DOM range and contributes nothing
  to stringification. No DOM change anywhere — painting only.

## Painting

No new paint code: the ellipsis is ordinary text in a `TextFragment`
(shaped glyphs + font key + metrics), painted by the existing text
path and clipped by the existing overflow clip nodes. `display_list`
and hit-test traversal need no changes beyond what shortened fragments
already imply.

## white-space / overflow interaction matrix (phase 1)

| white-space | overflow | behavior |
|---|---|---|
| nowrap | hidden/clip | truncate + ellipsis at boundary |
| nowrap | visible/scroll | truncate + ellipsis, overflowing visibly (Chrome parity) |
| normal/pre-wrap | any | only lines that actually overflow (unbreakable runs); wrapped lines break instead |
| pre | hidden | same as nowrap |

## WPT plan (css/css-overflow/text-overflow-*)

Nearly all are reftests (pixel comparison — the probe cannot
screenshot; they run in the pane screenshot harness). Probe-observable
contracts first (new `mozilla/text-overflow-ellipsis.html`):

1. Range rects of an overflowing line end within the container's
   content width (truncated), while the full text remains selected
   (`toString` returns everything).
2. RTL mirror: truncation at the visual left.
3. No-ellipsis control: `text-overflow: clip` keeps current behavior
   (overflow without marker).

Upstream reftests to run after (before/after counts in the row):
`text-overflow-ellipsis-001/002`, `-rtl-001`, `-width-001`,
`-ellipsis-003`, `-with-selection`, `-indent-001`, `-scroll-001`,
`-scroll-rtl-001`, `-change-color`, `text-overflow.html`,
`text-overflow-*-ref` companions as appropriate; `*-string-*`,
`*multiline*`, `*vertical*`, `*textarea*`, `*ruby*` stay phase 2
(string values, vertical writing, ruby, form controls).

## Phase 2 (explicitly out)

Two-value syntax (physical left/right sides), `<string>` values,
`line-clamp` multi-line ellipsis, vertical writing modes, form-control
internals, `text-overflow` on flex/grid containers beyond block
containers.
