#!/usr/bin/env python3
"""Nightly web-compat scoreboard: fork WPT vs upstream Servo vs Chrome.

Reads fork wptreport JSON files, fetches the nearest same-or-earlier
upstream-Servo and Chrome runs from wpt.fyi, and writes one data file plus
a static index page. Standard library only.

Method (also in scoreboard/README.md): pass rate = passed subtests /
total subtests, summed per area, exactly how wpt.fyi's summary files
count (their ``c: [pass, total]`` per test). Tests without subtests are
ignored on every side.
"""

import argparse
import gzip
import json
import os
import sys
import urllib.request

WPTFYI = "https://wpt.fyi"

# Pane-highlight areas first, then the overall row. Each maps to WPT path
# prefixes (leading slash). "downloads" has no dedicated suite: link
# navigation plus blob/file handling is the closest approximation.
AREAS = {
    "selection": ["/selection/"],
    "editing": ["/editing/", "/contenteditable/"],
    "css-overflow": ["/css/css-overflow/"],
    "range-geometry": ["/cssom-view/", "/css/cssom-view/"],
    "downloads": ["/html/links/", "/FileAPI/"],
    "user-activation": ["/html/user-activation/"],
}

UA = {"User-Agent": "legatus-scoreboard (nightly)"}


def area_of(test):
    for area, prefixes in AREAS.items():
        if any(test.startswith(p) for p in prefixes):
            return area
    return None


def tally():
    return {area: [0, 0] for area in AREAS}


def add(t, area, passed, total):
    t[area][0] += passed
    t[area][1] += total


def overall(t):
    p = sum(v[0] for v in t.values())
    n = sum(v[1] for v in t.values())
    return [p, n]


def fork_reports(paths):
    """Aggregate fork wptreport files: subtest PASS / total per area."""
    t = tally()
    n_files = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        n_files += 1
        for test in report.get("results", []):
            area = area_of(test.get("test", ""))
            if area is None:
                continue
            for sub in test.get("subtests", []):
                add(t, area, 1 if sub.get("status") == "PASS" else 0, 1)
    return t, n_files


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(gzip.decompress(raw))


def nearest_run(product, date):
    """Latest master run for product with time_start on or before date."""
    runs = http_json(
        f"{WPTFYI}/api/runs?label=master&product={product}&max-count=10"
    )
    for run in runs:
        if run.get("time_start", "")[:10] <= date:
            return run
    return runs[0]


def fyi_summary(run):
    """Aggregate a wpt.fyi run's summary file the same way (c=[pass,total])."""
    t = tally()
    summary = http_json(run["results_url"])
    if isinstance(summary, list):
        # Raw wptreport instead of a summary file: count like fork reports.
        for test in summary:
            area = area_of(test.get("test", ""))
            if area is None:
                continue
            for sub in test.get("subtests", []):
                add(t, area, 1 if sub.get("status") == "PASS" else 0, 1)
        return t
    for test, value in summary.items():
        area = area_of(test)
        if area is None:
            continue
        counts = value.get("c", [0, 0]) if isinstance(value, dict) else [0, 0]
        add(t, area, counts[0], counts[1])
    return t


def pct(pair):
    return round(100 * pair[0] / pair[1], 2) if pair[1] else None


def entry(t):
    return {
        area: {"pass": t[area][0], "total": t[area][1], "pct": pct(t[area])}
        for area in AREAS
    }


def render_html(data, history):
    """Static table: fork vs upstream vs Chrome + deltas, plus fork trend."""
    areas = list(AREAS)
    runs = data["runs"]

    def cell(side, area):
        v = runs[side]["areas"][area]
        return "n/a" if v["pct"] is None else f'{v["pct"]:.2f}% ({v["pass"]}/{v["total"]})'

    def delta(side, area):
        a, b = runs["fork"]["areas"][area], runs[side]["areas"][area]
        if a["pct"] is None or b["pct"] is None:
            return "n/a"
        d = round(a["pct"] - b["pct"], 2)
        return f'{"+" if d >= 0 else ""}{d:.2f}pp'

    rows = "\n".join(
        f"<tr><td>{a}</td><td>{cell('fork', a)}</td>"
        f"<td>{cell('upstream', a)}</td><td>{cell('chrome', a)}</td>"
        f"<td>{delta('upstream', a)}</td><td>{delta('chrome', a)}</td></tr>"
        for a in areas
    )
    f, u, c = (overall({a: [runs[s]["areas"][a]["pass"], runs[s]["areas"][a]["total"]]
                             for a in areas}) for s in ("fork", "upstream", "chrome"))
    def show(v):
        return "n/a" if v is None else f"{v}%"

    trend = "\n".join(
        f"<li>{h['date']}: {show(h['fork_overall_pct'])} "
        f"(upstream {show(h['upstream_overall_pct'])}, chrome {show(h['chrome_overall_pct'])})</li>"
        for h in history[-14:]
    )
    day = data["date"]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Legatus Servo web-compat scoreboard</title>
<style>body{{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse}}td,th{{border:1px solid #999;padding:.3rem .6rem;text-align:right}}
td:first-child,th:first-child{{text-align:left}}</style></head><body>
<h1>Web-compat scoreboard ({day})</h1>
<p>Fork <code>{runs["fork"]["sha"]}</code> vs upstream Servo
(<code>{runs["upstream"].get("version", "")}</code>) vs Chrome
(<code>{runs["chrome"].get("version", "")}</code>).
Pass rate = passed subtests / total subtests. Method: scoreboard/README.md.</p>
<table><tr><th>area</th><th>fork</th><th>upstream</th><th>chrome</th>
<th>fork&minus;upstream</th><th>fork&minus;chrome</th></tr>
{rows}
<tr><td><b>overall</b></td><td><b>{pct(f)}%</b></td><td><b>{pct(u)}%</b></td>
<td><b>{pct(c)}%</b></td><td></td><td></td></tr></table>
<h2>Fork trend (overall %)</h2><ul>{trend}</ul>
<p>Daily JSON: <a href="data/{day}.json">data/{day}.json</a></p>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--fork-sha", required=True)
    ap.add_argument("--reports", nargs="+", required=True)
    ap.add_argument("--history-dir", default=None)
    ap.add_argument("--out-data", required=True)
    ap.add_argument("--out-html", required=True)
    args = ap.parse_args()

    fork, n_files = fork_reports(args.reports)
    print(f"fork: {n_files} report(s), {overall(fork)} subtests", flush=True)
    upstream_run = nearest_run("servo", args.date)
    chrome_run = nearest_run("chrome", args.date)
    print(f"upstream: servo run {upstream_run['id']} ({upstream_run.get('time_start','')[:10]})", flush=True)
    print(f"chrome: run {chrome_run['id']} ({chrome_run.get('time_start','')[:10]})", flush=True)
    upstream, chrome = fyi_summary(upstream_run), fyi_summary(chrome_run)

    data = {
        "date": args.date,
        "fork_sha": args.fork_sha,
        "runs": {
            "fork": {"sha": args.fork_sha, "areas": entry(fork)},
            "upstream": {
                "run_id": upstream_run["id"],
                "version": upstream_run.get("browser_version", ""),
                "revision": upstream_run.get("revision", ""),
                "areas": entry(upstream),
            },
            "chrome": {
                "run_id": chrome_run["id"],
                "version": chrome_run.get("browser_version", ""),
                "revision": chrome_run.get("revision", ""),
                "areas": entry(chrome),
            },
        },
    }
    history = []
    if args.history_dir and os.path.isdir(os.path.join(args.history_dir, "data")):
        for name in sorted(os.listdir(os.path.join(args.history_dir, "data"))):
            if not name.endswith(".json") or name[:10] > args.date:
                continue
            with open(os.path.join(args.history_dir, "data", name), encoding="utf-8") as f:
                old = json.load(f)
            def opct(side):
                a = old["runs"][side]["areas"]
                p = sum(v["pass"] for v in a.values())
                n = sum(v["total"] for v in a.values())
                return round(100 * p / n, 2) if n else None
            history.append({
                "date": old["date"],
                "fork_overall_pct": opct("fork"),
                "upstream_overall_pct": opct("upstream"),
                "chrome_overall_pct": opct("chrome"),
            })
    history.append({
        "date": args.date,
        "fork_overall_pct": pct(overall(fork)),
        "upstream_overall_pct": pct(overall(upstream)),
        "chrome_overall_pct": pct(overall(chrome)),
    })
    with open(args.out_data, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(args.out_html, "w", encoding="utf-8") as f:
        f.write(render_html(data, history))
    print(f"wrote {args.out_data} and {args.out_html}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
