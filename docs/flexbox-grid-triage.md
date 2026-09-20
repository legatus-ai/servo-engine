# Flexbox / grid failure triage (sync-1 trees, WSL wptrunner)

Why these two first: the pane UI is React + full MUI, and MUI layout is
flexbox and grid almost everywhere — not the lowest scores, but the
highest-traffic for our product. See `scorecard.md`.

## Reachability verdict

Nearly everything below RAN in our harness (testharness asserts plus
pixel reftests, all headless-runnable). The reachable set is ~all of
it; unlike svg there is no rendering-backend wall here. What remains
is layout logic: abspos static positions, baseline alignment,
intrinsic sizing, and property interpolation.

## Flexbox: ~1480 failing subtests in 123 files + 21 failing reftests

| cluster | failing subtests | shape of the gap |
|---|---|---|
| abspos staticpos (`abspos/position-absolute-*`, `flex-abspos-staticpos-*`) | ~490 | static position of abspos children ignores align-self/justify-content, esp. vertical writing modes; `position-absolute-013` alone is 216/432 |
| alignment, vertical/baseline (`align-content-wmvert`, `flex-align-baseline-*`, multiline align-self) | ~330 | baseline alignment vs line-clamp/grid/multicol; vertical-WM align-self/content |
| negative overflow (`negative-overflow-00*`) | ~210 | negative-margin overflow reporting (002/003/004 near-total) |
| animation (`animation/order-interpolation`, `flex-*-interpolation`, composition) | ~195 | interpolation + composition of flex-grow/shrink/basis/order |
| intrinsic minimums (`flex-minimum-height-flex-items-031`, aspect-ratio-008) | ~50 | automatic minimum size edge cases |
| reftests (21 `.xhtml`: align-self-baseline/vert, basic-block vert, justify-content wmvert) | pixel | same baseline/vertical clusters, pixel form |

Plus 2 test-level unexpected FAILs (`align-self-horiz-001-block`,
`mbp-horiz-003v`) — expected PASS upstream, failing for us: look here
first, they may be one fix each.

## Grid: ~7100 failing subtests in 438 files, 0 failing reftests

| cluster | failing subtests | shape of the gap |
|---|---|---|
| abspos positioned descendants (`abspos/orthogonal-positioned-*`, `positioned-grid-descendants-*`, staticpos) | ~3090 | orthogonal flows + static positions; dozens of files at 95-100/100 failing — systematic, likely few root causes |
| track sizing (`grid-lanes/track-sizing`, `intrinsic-sizing`, flex-track intrinsic sizes) | ~1700 | intrinsic/max-content track sizing incl. flex tracks |
| alignment (`alignment/*`, baseline, self-baseline) | ~870 | same baseline family as flexbox |
| animation (`grid-template-*-interpolation`, composition, `grid-lanes/animation/*`) | ~770 | grid-template rows/columns interpolation + flow-tolerance (240/240 in one file) |
| subgrid (`grid-lanes/subgrid`, baseline, invalidation) | ~200+ | subgrid track sizing/alignment |
| item placement (`grid-lanes/item-placement`, tentative) | ~150 | auto-placement edge cases |
| parsing (`parsing/*`) | 137 | property parsing rejections |

Plus 1 unexpected-pass (`flex-track-intrinsic-sizes-003` OK vs TIMEOUT)
and 1 reproducible CRASH (`selectors/invalidation/has-complexity.html`,
recorded in the scorecard).

## Suggested build order (when the work starts)

1. Abspos staticpos in flex AND grid (largest clusters, systematic —
   likely shared root causes in static-position resolution).
2. Baseline alignment incl. vertical writing modes (spans both).
3. Intrinsic track/item sizing (grid-lanes + flex minimums).
4. Interpolation of flex/grid-template properties (animation cluster).
5. The 2 flexbox unexpected FAILs (may fall out of 1-2).

Method: per-dir foreground wptrunner runs (BUILDING.md rules),
`--log-raw` parsed at `test_status` level, clustered by parent dir.

## Horizontal-tb LTR filter (the pane-relevant gap)

Raw percentages overstate our problem: the pane is horizontal-tb LTR.
Filtered split — (a) files with no vertical/WM content, (b)
WM/direction-attributed subtests, (c) ambiguous (mixed-mode file,
unattributed subtest):

- Flexbox: (a) 335 subtests / 44 files, (b) 688, (c) 459. The (a)
  list is led by animation interpolation (order/flex-grow/basis/
  shrink + composition + discrete ≈ 195, low product relevance —
  static MUI rarely animates flex properties), then automatic
  minimums (flex-minimum-height-031: 36), baseline alignment
  (~30), intrinsic sizing/parsing (~40), and the abspos
  physical-justify family (~10). Product-relevant core ≈ 140
  subtests plus (c)'s horizontal share — small enough to work
  through, and NOT the abspos-vertical story.
- Grid: (a) 3812 subtests / 213 files, (b) 2850, (c) 429. The (a)
  list is led by abspos staticpos against grid AREAS
  (`positioned-grid-descendants-*`, ~90-99 failing subtests EACH —
  popovers/menus/overlays in grid areas, directly product-relevant),
  flex-track intrinsic sizes (204), track-sizing (89), grid-template
  interpolation (~460, low relevance like flexbox), and parsing.
  Unlike flexbox, grid's horizontal gap is LARGE and concentrated:
  grid-area abspos staticpos first, then intrinsic track sizing.

Verdict on the expectation: confirmed for flexbox (practical backlog
is small), destroyed for grid (the horizontal gap is real, ~3800
subtests, led by abspos-in-grid-area). MUI data grids will feel this;
flexbox mostly will not.
