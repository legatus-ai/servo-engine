# Legatus WPT scorecard

Trend line, one row per sync. A partial scorecard labelled honestly beats
a total that hides its denominator.

## Methodology (sync-1)

- Ours: WSL Ubuntu-24.04, `Servo 0.6.0-b5a1f5e6ec6` dev servoshell built
  from this branch (sync-1 tree), `./mach test-wpt --processes 4`,
  `--log-raw` parsed at subtest level. Counts are raw `PASS/total`
  subtests; reftests contribute test-level only. `unexpected` = test
  results differing from the in-tree expectations (FAIL/TIMEOUT/CRASH
  vs PASS, or unexpected passes).
- Upstream Servo: wpt.fyi run `5132545661599744`
  (`0.6.0-0f4d68e09`, 2026-09-18) — our exact fork point, same
  wptrunner/subtest methodology, directory-scoped identically. The
  servo.org dashboard (scores.json, product `0.6.0-b5a1f5e6e` = our
  sync rev) uses expectation-weighted scoring and is not mixed in.
- Chrome stable: wpt.fyi run `5171365757059072` (153.0.8010.52,
  2026-09-19), same directory scopes and raw-subtest counting.
- WPT revisions drift between the three runs, so small denominator
  differences are tree drift, not signal. Deltas under ~1pp are noise.

## Sync-1 (2026-09-20): ours vs upstream vs Chrome, subtests pass/total (%)

| area | ours (legatus) | upstream Servo | Chrome stable | ours unexpected |
|---|---|---|---|---|
| css-flexbox | 3271/4753 (68.8%) | 3271/4753 (68.8%) | 4444/4480 (99.2%) | 2 FAIL |
| css-grid | 7697/14788 (52.0%) | 6607/13426 (49.2%) | 12864/14345 (89.7%) | 1 unexpected-pass |
| css-overflow | 597/1169 (51.1%) | 594/1180 (50.3%) | 1017/1112 (91.5%) | 16 |
| css-text | 3235/4673 (69.2%) | 3235/4673 (69.2%) | 5022/5695 (88.2%) | 19 |
| selectors (css/selectors) | 4006/6066 (66.0%) | 4007/6071 (66.0%) | 5087/6058 (84.0%) | 1 up-pass + 1 CRASH (has-complexity, reproduces solo) |
| variables (css/css-variables) | 461/588 (78.4%) | 458/588 (77.9%) | 512/584 (87.7%) | 0 |
| cssom-view | 1504/2211 (68.0%) | 1454/2211 (65.8%) | 1850/2151 (86.0%) | 0 |
| dom-events | 748/893 (83.8%) | 752/895 (84.0%) | 852/888 (95.9%) | 0 |
| editing | 91911/115308 (79.7%) | 91919/115793 (79.4%) | 97662/106730 (91.5%) | 2 TIMEOUT (1 flake, passes solo; 1 real: forwarddelete.tentative) |
| selection | 34189/34419 (99.3%) | 34129/34419 (99.2%) | 34351/34413 (99.8%) | 0 |
| forms (html/semantics/forms) | 4542/5241 (86.6%) | 4542/5247 (86.6%) | 4980/5269 (94.5%) | 1 CRASH (disabled-003) + 1 FAIL-vs-ERROR |
| svg | 824/4438 (18.6%) | 776/4466 (17.4%) | 5499/5970 (92.1%) | 2 TIMEOUT |
| fetch | 9472/11124 (85.2%) | 9424/11225 (84.0%) | 11809/12652 (93.3%) | 20 (mostly big-body TIMEOUTs) |
| xhr | 2089/2258 (92.5%) | 2088/2258 (92.5%) | 2137/2281 (93.7%) | 0 |
| clipboard-apis | 115/247 (46.6%) | 112/247 (45.3%) | 171/184 (92.9%) | 0 |
| contenteditable | 5/6 (83%) | n/a | n/a | 0 |

Legatus mozilla contracts under the same harness: 8/8 testharness files
OK with zero unexpected subtests; `#48149` image reftests PASS x2;
upstream `text-overflow-ellipsis-stacking-context` FAILs as its ini
expects (phase-2 work). Native-input contracts (dblclick composition,
native dblclick) are pane-harness tier, not counted here.

## Notables

- Our #7 ellipsis moves upstream css-overflow tests: `text-overflow-029`,
  `-022`, `-ellipsis-001`, `-ellipsis-rtl-001`, `-007`, `-012`, `-014`
  now PASS against expected FAIL. Still failing (phase 2): indent,
  editable-div-with-caret, two-value cases (`-009`, `-016`).
- Reproducible crashes (recorded, out of scope for sync-1):
  `selectors/invalidation/has-complexity.html`,
  `forms/the-fieldset-element/disabled-003.html`.
- svg at 18.6% is the honest floor: most svg tests are pixel reftests
  against a backend Servo barely implements.

## Deliberately not run

Everything outside the focus dirs (full WPT is ~58k tests): html
outside forms, css outside the listed modules, dom outside events,
workers, crypto, media, etc. Perf (Speedometer) deferred: needs a
scripted harness that does not exist yet.

## Prioritised next: flexbox + grid (pane MUI dependency)

Not because they are the lowest scores (svg is lower) but because they
are the highest-traffic for our own product: the pane UI is React +
full MUI, and MUI layout is flexbox and grid almost everywhere. A
30-point flexbox gap is the probability that a card, a dialog, or a
data grid renders wrong in Gary's pane. These two rows get attention
ahead of svg; see `docs/flexbox-grid-triage.md` for the failure
clusters.

## Reproduce

Per-dir foreground runs (see BUILDING.md long-batch rules):
`./mach test-wpt --no-manifest-update --processes 4 --log-raw <log>
<dirs...>` then aggregate `test_status` PASS/total by directory.
wpt.fyi columns: `/api/search?run_ids=<id>&q=<dir>`, keep results whose
test starts with `/<dir>/`, sum `legacy_status` passes/total.

## Methodological lesson (sync-1 triage)

A raw conformance percentage answers how COMPLETE the engine is, not
how well OUR product will render. The pane is horizontal-tb LTR
English, so ~480 of ~1480 flexbox failures (vertical writing-mode
symptoms of one flow bug) can never affect what Gary sees — yet they
dominate the headline gap. The second question needs the
writing-mode/direction filter applied BEFORE the number means anything
to us: split failing subtests into (a) horizontal-only files,
(b) WM/direction-attributed, (c) ambiguous (mixed-mode file,
unattributed subtest). True product gap lies in (a) plus (c)'s
horizontal share. See `docs/flexbox-grid-triage.md`.

## How determinism was checked (not assumed)

Full-dir numbers are compared as UNIQUE (test, subtest) sets
(last-wins), never raw line counts — duplicate log lines made two
runs look different when the sets were identical. Repeatability was
measured, not assumed: one 4-file scope run six times (three at
--processes 1, three at --processes 4) gave bit-identical results
(57/303/0/360) every time, and a full css-grid re-run against baseline
gave zero set-delta (7697/14788 both sides, 0 newly passing, 0 newly
failing). Process count is not the variable; scope must still match
exactly (solo-vs-full-dir differences are scope effects, and the
zz-rects ERROR in one run was a deleted scratch file lingering in the
local manifest, not signal).
