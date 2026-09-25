# Design note: `text-overflow: ellipsis` (Legatus #7, phase 1)

Status: APPROVED by Vitruvius with 3 amendments (incorporated below).
Phase 1: single-line `ellipsis` at the logical end. Phase 2: two-value
syntax, `<string>` values, `overflow: scroll|auto` dynamics, line-clamp,
vertical writing, form controls.

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

## Gate (amended per review — spec css-overflow-3 §6.1)

> "This property specifies rendering when inline content overflows its
> end line box edge ... of its block container element ('the block')
> **that has overflow other than visible**."

Truncate a line only when all hold on the block container style:

- `text-overflow` second side (logical end) is `Ellipsis` (phase 1;
  `String(_)` and two-value physical sides are phase 2),
- the block's `overflow-x` (inline axis) computes to something other
  than `visible` — i.e. `hidden` or `clip` in phase 1,
- the line's content inline size exceeds the available inline size
  (after float adjustment),
- the line is not a phantom line.

`overflow-x: scroll|auto` is phase 2, not phase 1: per spec
§"ellipsis interaction with scrolling interfaces", scrolling must
re-reveal content and shrink the ellipsis dynamically
(text-overflow-scroll-001), which needs scroll-offset-aware truncation
— layout does not re-run on scroll, so a layout-baked ellipsis would
go stale. `overflow: visible` gets no ellipsis at all (Chrome/Firefox
parity — the earlier draft of this note was wrong here).

## Truncation algorithm (visual order, from the visual end) —
amended: grapheme clusters, block-styled ellipsis

Line items hold shaped glyphs (`TextRunLineItem.text:
Vec<Arc<ShapedTextSlice>>` with `total_advance()`), so truncation is
glyph arithmetic, mirroring the existing `trim_whitespace_at_end`
pattern in `line.rs`. Per spec, "character" means grapheme cluster
(UAX29): never split combining-mark sequences, emoji ZWJ sequences,
regional-indicator pairs, or ligature clusters.

1. Shape the ellipsis run once per distinct font: U+2026 with the
   **block container's used font** (spec: "The ellipsis is styled and
   baseline-aligned according to the block"), measure its advance E.
   If the block font lacks the glyph, fall back to "..." (three
   U+002E) in the same font.
2. Walk trailing line items from the visual end, dropping whole items
   (atomic inlines; trailing padding/border/margin markers stay — only
   content items go), then truncating inside the last text item at a
   **grapheme-cluster boundary** (use the glyph→character cluster
   mapping from shaping; a slice can span a whole word, so dropping
   whole slices would leave a visible gap). Drain whole clusters from
   the visual end until the freed space fits E.
3. If even the first character plus E overflows, **clip, don't
   ellipsis** (spec: "The first character or atomic inline-level
   element on a line must be clipped rather than ellipsed"; likewise
   clip the ellipsis itself when space is insufficient).
4. Shorten the last surviving text item in place (drain trailing
   clusters) and append the ellipsis slices as a new trailing
   `LineItem::TextRun` with an **empty**
   `character_range_in_dom_node`, so no DOM text claims the ellipsis.
   Baseline-align per the block's metrics (the ellipsis fragment uses
   the block font metrics for its line-box contribution).

Inline boxes (spans): truncation crosses box boundaries freely — boxes
contribute no width themselves, only their text children do. The
ellipsis does NOT inherit the truncated inline's style (spec:
block-styled). Inline-blocks and other atomics at the visual end are
dropped whole (they cannot be partially shown); floats/abspos
placeholders are skipped, never truncated. Truncation is computed in
layout space; relative positioning and transforms apply uniformly at
paint as usual.

## Ellipsis glyph sourcing

- U+2026 shaped with the **block container's used font** (spec §6.1:
  "styled and baseline-aligned according to the block"), first font in
  its font list that has the glyph.
- If the block font lacks the glyph, shape "..." (three U+002E) in the
  same font (spec: "or three dots "..." if the ellipsis character is
  unavailable"; other scripts/writing modes may substitute a more
  appropriate ellipsis — out of phase 1).
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

## white-space / overflow interaction matrix (phase 1, amended)

| white-space | overflow-x | behavior |
|---|---|---|
| nowrap | hidden/clip | truncate + ellipsis at boundary |
| nowrap | visible | NO ellipsis, text overflows visibly (spec: block must have overflow other than visible) |
| nowrap | scroll/auto | phase 2 (dynamic re-reveal while scrolling) |
| normal/pre-wrap | hidden/clip | only lines that actually overflow (unbreakable runs); wrapped lines break instead |
| pre | hidden/clip | same as nowrap |

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
`overflow-x: scroll|auto` dynamics (re-reveal while scrolling),
`line-clamp` multi-line ellipsis, vertical writing modes, form-control
internals, `text-overflow` on flex/grid containers beyond block
containers.
