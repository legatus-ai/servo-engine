# Design note: upstream sync + Chrome scorecard (standing jobs)

Status: proposed, awaiting Vitruvius review. No code, no syncs run yet.

## 1. Upstream sync

### What syncs, from where, how often

- `servo-engine`, branch `legatus` ← `servo/servo` `main`, weekly
  (merge, not rebase — history stays reviewable).
- `../stylo`, branch `legatus` ← `servo/stylo` `main`, same day, first
  (engine follows; re-apply the `longhands.toml` text-overflow hunk if
  the merge loses it — the hunk is one line, commit `b26e41f`).
- Our changes stay a small labelled patch series: every legatus commit
  message carries `Legatus #N` (already the convention). Anything not
  traceable to a request row gets reverted or re-tagged during the sync.

### Per-sync verification (all green before the merge lands)

1. `cargo build` of the engine as consumed downstream (see constraints).
2. Our regression tests: every `tests/wpt/mozilla/tests/mozilla/*`
   file we added, run under testharness via the probe runner
   (`assemble_one.ps1` + `read_wpt.js`), all passing.
3. Tracked upstream subsets (probe-runnable, testharness-based):
   `selection/modify*.tentative.html`, `css/cssom-view/CaretPosition-001`,
   `css/cssom-view/range-*`, `css/cssom-view/cssom-getClientRects*`,
   `svg/styling/presentation-attributes-*`, plus any new subset a
   request adds (e.g. `css/css-overflow` testharness-runnable files;
   reftests go to the pane screenshot harness).
4. Record in `docs/legatus-requests.md` (Log section): sync date,
   upstream servo rev, upstream stylo rev, conflicts (files + how
   resolved), and the test results above.

### Drop-our-patch rule

If upstream fixes something we patched (same behavior, upstream tests
green), revert our implementation commit, keep our regression test,
and note the superseding upstream commit in the row. Default on close
calls: ask Vitruvius rather than guess.

### Known constraints (discovered during #1–#7)

- This checkout has no `ffi/` dir, so `cargo` with
  `servo-engine/Cargo.toml` as manifest fails at load. All builds run
  through downstream workspaces (today the runtime probe). The sync
  verification build therefore depends on a cooperating downstream
  manifest — which the engine side must not modify. Concretely: the
  pane/renderer workspace must carry the same stylo `[patch]` (row #7
  notes this) or verification builds silently test upstream Stylo.
- No servoshell build exists on this machine (no `target/` in
  servo-engine; a first build is 40+ min and webdriver/wptrunner flow
  is unproven here). Full-WPT runs are pane-CI territory; the sync
  gate above is the probe-runnable subset, stated as such.
- Path `[patch]` entries require the sibling checkout layout
  (`../servo-engine`, `../rust-url`, `../stylo`). Documented in the
  workspace `Cargo.toml` comment; any new consumer needs the same
  siblings.

## 2. Scorecard (`docs/scorecard.md`, updated every sync)

One table per focus area; each sync appends a dated row
(date, our rev, upstream rev). Columns per area:

| area | ours (probe subset) | upstream Servo | Chrome stable |
|---|---|---|---|

Focus areas (per brief): css flexbox, css grid, css overflow, css text,
css selectors, css variables, cssom-view, dom/events, editing/selection,
html forms/input, svg, fetch/xhr, clipboard-apis.

Data sources:

- Ours: probe-run subsets only (the §1.3 list plus per-area additions
  as implemented). Counts are exact for the listed files, not
  extrapolated — the scorecard states the file list per area.
- Upstream Servo: `wpt.servo.org` (fallback: results linked from
  servo.org/wpt). Same area/file scope as ours where possible.
- Chrome stable: `wpt.fyi` for the same files.
- Overall WPT rate: not feasible on this machine (no full harness);
  report the aggregate over our tracked subset, labelled as such —
  a trend line over a fixed set beats a one-off estimate.
- Perf (optional): Speedometer 3 needs a scriptable browser harness
  (servoshell + webdriver), which does not exist here today.
  Recommendation: defer until the pane harness or a local servoshell
  can drive it; do not hand-roll a benchmark.

The aim is the trend, not a snapshot: identical file lists and
commands every sync, deltas highlighted, regressions fail the sync.

## 3. Open questions for review

1. Cadence owner: does the goal loop run the sync weekly, or on demand?
2. Full-subset runs: will pane CI run the tracked subsets (and the
   pixel reftests) per sync, with results fed back here?
3. Drop-patch authority: mine on clear upstream equivalence, else ask?
4. Speedometer: defer as recommended, or stand up servoshell here?
