# Web-compat scoreboard

Nightly WPT pass rates: the fork (`legatus` branch, release, headless) vs
upstream Servo vs Chrome. The page has two tables: the extra areas with an
overall row, and one row per CSS module with an "all CSS" totals row. It
also shows fork-minus deltas and a 14-day fork trend. Everything is
published to the `scoreboard` branch (`data/YYYY-MM-DD.json`,
`data/YYYY-MM-DD-gaps.json` and `index.html`), which Pages serves at
https://legatus-ai.github.io/servo-engine/.

## Method

- Pass rate = passed subtests / total subtests, summed per area or module.
  This is how wpt.fyi counts: its per-run summary files carry
  `c: [pass, total]` subtest counts per test, and the generator aggregates
  those identically.
- Tests without subtests (reftests, crashtests) have `c: [0, 0]` on
  wpt.fyi, so they add nothing to subtest counts on any side. Most of CSS
  is reftests, so the module table also shows them separately as
  "no-subtest" passed/total by harness status (skipped tests excluded).
- Fork numbers come from the workflow's own `./mach test-wpt --release
  --headless` `--log-wptreport` shards, merged.
- Upstream and Chrome numbers come from the wpt.fyi API only
  (`/api/runs` for the latest `master` run of `product=servo` /
  `product=chrome`, then that run's summary file). The fork SHA never
  appears on wpt.fyi, so alignment is nearest-date on-or-before the fork
  date; each data file records both revisions.
- Only `GITHUB_TOKEN` is used. No Chrome is ever executed here.

## What runs

- Nightly (06:00 UTC) and manual dispatch with empty inputs: the whole
  `css/` directory plus `selection editing contenteditable html/links
  FileAPI html/user-activation`, in 16 shards (`NIGHTLY_WPT_SUBSETS` and
  `NIGHTLY_CHUNKS` in the workflow). mach chunks by test-id hash, so the
  shards are even. Each shard has a 120-minute job timeout; the last
  measured rate puts a shard at roughly 20-35 minutes.
- Manual dispatch can pass its own `wpt-subsets` (space-separated WPT
  paths, or `all` for the full suite) and `chunks` (1..20).
- Shards run with `fail-fast: false`. The page is generated from whatever
  shards produced a readable, non-empty report, and any missing shard is
  named on the page and in the data file (`shards.missing`).

## CSS modules

A CSS module is the second path segment of a `/css/<module>/...` test
(`css-flexbox`, `css-grid`, `CSS2`, `selectors`, ...). Rows are sorted by
gap to Chrome in subtests (Chrome passed minus fork passed), largest first.
Modules the fork did not run show "not run" and sort last.

## Gap list

`data/YYYY-MM-DD-gaps.json` holds the top 50 CSS tests the fork ran where
Chrome passes more subtests than the fork, ranked by that per-test subtest
gap and grouped by module (groups sorted by their summed gap). Each entry
has fork, upstream and Chrome subtest counts. `candidates` is how many
tests had any gap; `no_subtest_failures` counts, per module, the
reftests/crashtests Chrome passes and the fork fails, since those have no
subtest gap to rank.

## Areas

Pane-highlight areas map to WPT path prefixes (`scoreboard/generate.py`
`AREAS`): `selection/`, `editing/` + `contenteditable/`,
`css/css-overflow/`, `cssom-view/` + `css/cssom-view/` (range geometry),
`html/links/` + `FileAPI/` (downloads: link navigation plus blob/file
handling, since no dedicated downloads suite exists), `html/user-activation/`.

## Files on `main`

- `.github/workflows/scoreboard.yml` (registered from `main`, builds and
  tests the `legatus` branch). Never runs on `pull_request`.
- `.github/workflows/scoreboard-tests.yml`: runs the scorer's unit tests
  on PRs that touch the scorer or workflow.
- `scoreboard/generate.py`: stdlib-only scorer and static page renderer.
- `scoreboard/test_generate.py` and `scoreboard/testdata/`: unit tests
  (`python3 -m unittest discover -s scoreboard -p 'test_*.py'`).
- This README.
