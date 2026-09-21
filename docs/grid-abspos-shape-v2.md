# Shape note v2: grid-area abspos containing block

SUPERSEDES the abspos/verticalWM shape note from 2026-09-19 (the one
that led CB narrowing with "fully definite placement" and, before that,
presumed static-position drift). The v2 note's three sub-shapes
survived partially; its recommendation sequence did not. This file
records what actually worked, why, and the cul-de-sac that cost a
night — so the next person neither repeats it nor inherits it blind.

## Status of the fix (measured, identity-proven)

Full `css/css-grid` directory, worktree clean at the measured commit,
binary newer than sources, every diff hunk accounted applied-or-skipped:

- BEFORE 7697/14788 (52.0%), AFTER 7723/14788 (+26), newly FAILING 0.
- Gains: `grid-positioned-items-content-alignment-001` (+12) and
  `-rtl-001` (+12), two singles.

## The gate that works (all three conditions load-bearing)

An abspos grid child gets its grid AREA as containing block only when:

1. **Placement is fully definite** — all four `grid-row/-column` sides
   are plain or named lines (no `auto`, no `span`). Half-auto placements
   regressed single-inset tests: taffy's Auto-side fallback resolves
   against the padding box, not the spec's area-relative position.
2. **At least one inset is explicit.** All-auto insets must stay on
   container behavior — the stored static-position rect lives in the
   container frame, and narrowing the CB while keeping it makes
   fit-content sizing mix frames (text wrapped, regressions in the
   first wave). At least one explicit inset means the static rect does
   not enter the axis solver, so the trick is safe.
3. **The container is not a scroll container.** Taffy sizes tracks
   inside the scrollbar gutter but the abspos grid area extends across
   it; reconciling the two frames is separate, open work.

## The mechanism

Narrow at COLLECT time, not hoist time:

- `HoistedAbsolutelyPositionedBox` carries an optional narrowed CB size
  plus the area origin; `layout_as_absolute` takes a `final_translate`
  and applies it to the final rect; `LayoutRootLayoutInputs` records
  both so incremental relayout lands in the same frame.
- Collect time is where both direct grid children (taffy branch) and
  abspos nested inside grid *items* (hoisted through
  `flow/inline/line.rs`, the dominant route — the items mix text and
  abspos) converge, with the grid fragment's real border/padding box
  and its `SpecificLayoutInfo::Grid` available. Entry-point trace
  evidence: failing cases arrive as `collect: grid_info=true, boxes=2`;
  `flow/mod.rs` block-hoist never fires for these tests.

## The cul-de-sac (do not repeat)

The first working narrowing broke single-inset cases; I gated it to
ALL-explicit insets to stop the regression and committed the message
"single-auto regressed" — without joining it with the second fact: the
failing corpus IS the single-auto/half-auto set, so the gate excluded
the entire target. Eighteen commits of refinement then moved nothing,
because they refined a path no failing test executes. Zero-newly-passing
was true and nobody could name the reason until a one-line counter
proved the narrowing fired nowhere in the failing corpus. The counter —
not a better hypothesis, a COUNTER — broke the deadlock in one run
after eighteen commits of bisection failed to.

## The eighteen commits, kept as the map of the cul-de-sac

- Narrowing only fires with all-explicit insets (then) / the gate must
  allow any-explicit insets (now) — the single-auto regression was
  real, and its mechanism is now understood: static rect (container
  frame) paired with an area CB mixes frames on the auto axis.
- The single-auto case REGRESSED with narrowed CB + container-frame
  static rect; the fix shape for it is staticpos expressed in the AREA
  frame from the start, not a post-hoc translate.
- Degenerate grid areas (taffy collapses abspos-only implicit tracks)
  must be skipped or insets collapse the box.
- The alignment overwrite (container align/justify-items rollover) is
  provably irrelevant to the tracked tests — the existing hoist-site
  resolution is already correct.
- Verbatim placement passthrough beats line-number normalization:
  synthesizing `end-1` lines produced invalid line 0 and regressed
  half-auto placements.
- `container_style` borrows must come out of the layout loop (`&mut`
  fragment borrows don't nest).
- Entry/hoist route: items mix text and abspos, so children hoist via
  `flow/inline/line.rs`; direct children would take the taffy branch;
  `flow/mod.rs` never fires here.

## Open follow-ups (named, not hidden)

- Scroll containers: track sizes exclude the gutter, the abspos area
  includes it. Needs one agreed frame.
- Half-auto lines (one side auto): needs staticpos-in-area-frame.
- All-auto insets: current behavior may already be right (flow
  staticpos); confirm against Chrome before touching.
