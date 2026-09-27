# Real-site benchmark: Servo vs Chrome

Nightly speed and stability measurement of the Legatus Servo fork (`legatus`
branch) against a pinned headless Chrome, on about 30 pinned snapshots of real
pages. Published at
<https://legatus-ai.github.io/servo-engine/realsites.html>, next to the
WPT scoreboard (`index.html`).

## What is measured

For each site, and for both Servo (headless servoshell) and Chrome for Testing
(pinned in `install-chrome.sh`), three runs, each a fresh browser process with an
empty profile (cold):

| Metric | How |
| --- | --- |
| Load | The page's own `loadEventStart` (Navigation Timing 2, falling back to Level 1). Median of 3. |
| First paint | Paint Timing `first-paint`, else `first-contentful-paint`, when the engine reports it. Median of 3. |
| Crash | Non-zero exit or signal, a panic line on stderr (servoshell runs with `--hard-fail`), or a WebDriver report of a dead page or browser. |
| Hang | No load event within 60 s (WebDriver page-load timeout, or the driver stops answering). |
| Visual | Viewport screenshot at 1280x800, device pixel ratio 1, 2 s after load. Percentage of pixels where any channel differs from Chrome's by more than 32/255. Thumbnails of the worst 10. |

A site's status is its worst run (crash > hang > error > ok). Medians use the
runs that produced a number. Headline numbers:

- **Load ratio**: median over sites of Servo load / Chrome load (lower is better).
- **Crash rate**: share of measured sites where Servo crashed in at least one run (hang rate likewise).
- **Median visual diff** across sites.

Both browsers are driven through the same W3C WebDriver calls
(`rs/webdriver.py`): servoshell's built-in `--webdriver` server and the pinned
chromedriver. The benchmark runs inside a network namespace that only has
loopback, so a snapshot that still references the live web fails fast instead
of timing the network.

Scroll and animation smoothness are not measured yet (see Follow-ups).

## Files

| Path | Role |
| --- | --- |
| `sites.json` | The pinned site list: id, category, source URL, license, whether scripts are kept. |
| `snapshots/<id>.html` | Self-contained snapshots (SingleFile), plus `snapshots/MANIFEST.json`. |
| `bench.py` | Runs every site, writes `raw.json` and screenshots. |
| `report.py` | Aggregates, diffs, validates, writes `data/realsites-<date>.json`, `realsites.html`, thumbnails. |
| `capture.py` | Captures snapshots (CI only, via `realsites-capture.yml`). |
| `rs/` | Pure parts (medians, classification, pixel diff, schema) and the WebDriver client. |
| `tests/` | Unit tests: `cd realsites && python -m unittest discover -s tests -t .` |
| `pane-host.html` | Host page for the private pane UI bundle (see below). |

Workflows: `.github/workflows/realsites.yml` (nightly at 08:30 UTC, and
manual), `realsites-capture.yml` (manual snapshot refresh),
`realsites-tests.yml` (unit tests on pull requests).

The Servo binary is not built here: `realsites.yml` downloads the newest
unexpired `scoreboard-binary` artifact that `scoreboard.yml` uploads (or the
one from a given run id), and records that run id and the `legatus` commit it
built.

## Refreshing the snapshots

Snapshots are captured in CI, never on a workstation:

1. Edit `sites.json` if the list changes (ids are `[a-z0-9-]`; note the license).
2. Run the **Real-site snapshot capture** workflow (Actions tab, or
   `gh workflow run realsites-capture.yml -R legatus-ai/servo-engine`,
   optionally with `-f only=site-a,site-b`).
3. Download the `realsites-snapshots` artifact
   (`gh run download <run-id> -R legatus-ai/servo-engine -n realsites-snapshots -D realsites/snapshots`),
   check the pages and `MANIFEST.json`, and commit them in a PR.

`capture.py` drops any page over 4 MB (resources over 1 MB are left out of the
page) and fails if the total exceeds 48 MB, which keeps the committed set
under about 50 MB. Sites with `"scripts": true` keep their JavaScript (SPAs,
dashboards, the store demo); the rest are saved as rendered by Chrome, with
scripts removed. Both engines always load the identical file, so any capture
artifacts affect Servo and Chrome equally.

## The pane's dashboard shell

`legatus-ai/legatus-terminal-pane` is private, so its UI bundle
(`ui/dist/pane.js`) is not committed to this public repo. When the
`PANE_DEPLOY_KEY` secret (a read-only deploy key on that repo) is set,
`realsites.yml` fetches the bundle at run time and serves it with
`pane-host.html`; otherwise the `legatus-pane-shell` site is reported as
skipped.

## Sources and licenses

Each entry in `sites.json` names its source URL and license. The list prefers
openly licensed or public pages (Wikipedia, Wikinews, GOV.UK under the Open
Government Licence, NASA, MDN, W3C and WHATWG specs, Rust, Python and Node.js
docs, MIT-licensed demos). A few pages whose site chrome is proprietary
(GitHub, the Shopify demo store, Hacker News) are kept only as interoperability
test fixtures, as noted in their entries.

## Follow-ups

- Scroll and animation smoothness (frame times during a scripted scroll, CSS animation jank).
- Link `realsites.html` from the WPT scoreboard page (`scoreboard/generate.py` owns `index.html`).
