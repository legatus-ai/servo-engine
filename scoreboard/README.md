# Web-compat scoreboard

Nightly WPT pass rates: the fork (`legatus` branch, release, headless) vs
upstream Servo vs Chrome, per top-level area plus an overall row, with
fork-minus deltas and a 14-day fork trend. Published to the `scoreboard`
branch (`scoreboard/data/YYYY-MM-DD.json` + `scoreboard/index.html`);
serve that branch with Pages.

## Method

- Pass rate = passed subtests / total subtests, summed per area. This is
  how wpt.fyi counts: its per-run summary files carry `c: [pass, total]`
  subtest counts per test, and the generator aggregates those identically.
  Tests without subtests are ignored on every side.
- Fork numbers come from the workflow's own `./mach test-wpt --headless`
  `--log-wptreport` shards (4 chunks, `--chunk-type hash`), merged.
- Upstream and Chrome numbers come from the wpt.fyi API only
  (`/api/runs` for the latest `master` run of `product=servo` /
  `product=chrome`, then that run's summary file). The fork SHA never
  appears on wpt.fyi, so alignment is nearest-date on-or-before the fork
  date; each data file records both revisions.
- Only `GITHUB_TOKEN` is used. No Chrome is ever executed here.

## Areas

Pane-highlight areas map to WPT path prefixes (`scoreboard/generate.py`
`AREAS`): `selection/`, `editing/` + `contenteditable/`,
`css/css-overflow/`, `cssom-view/` + `css/cssom-view/` (range geometry),
`html/links/` + `FileAPI/` (downloads: link navigation plus blob/file
handling — no dedicated downloads suite exists), `html/user-activation/`.

## Files on `legatus`

- `.github/workflows/scoreboard.yml` — nightly 06:00 UTC + manual
  (`workflow_dispatch` with optional WPT subset filter and chunk count).
  Never runs on `pull_request`. Reuses `linux.yml` (release build with
  sccache on forks) and `linux-wpt.yml` (shard matrix, merged
  `wpt-full-logs-linux` artifact), then generates and pushes.
- `scoreboard/generate.py` — stdlib-only scorer + static page renderer.
- This README.
