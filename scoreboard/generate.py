#!/usr/bin/env python3
"""Nightly web-compat scoreboard: fork WPT vs upstream Servo vs Chrome.

Reads fork wptreport JSON files, fetches the nearest same-or-earlier
upstream-Servo and Chrome runs from wpt.fyi, and writes one data file, one
gap list and a static index page. Standard library only.

Method (also in scoreboard/README.md): pass rate = passed subtests /
total subtests, summed per area or CSS module, exactly how wpt.fyi's
summary files count (their ``c: [pass, total]`` per test). Tests without
subtests (reftests, crashtests) carry ``c: [0, 0]`` there and add nothing
to subtest counts on any side; they are reported separately by harness
status so CSS, which is mostly reftests, is not invisible.
"""

import argparse
import gzip
import html
import json
import os
import re
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

# How many failing tests the gap list keeps.
GAP_LIMIT = 50

UA = {"User-Agent": "legatus-scoreboard (nightly)"}

# wptreport statuses -> wpt.fyi summary letters.
STATUS_LETTER = {
    "PASS": "P", "FAIL": "F", "OK": "O", "TIMEOUT": "T", "ERROR": "E",
    "CRASH": "C", "SKIP": "S", "NOTRUN": "N",
    "PRECONDITION_FAILED": "F", "PRECONDITION_FAIL": "F",
}
# Harness statuses that count toward a no-subtest test's pass/fail total.
# Skipped, not-run and OK-without-subtests are neither.
COUNTED = {"P", "F", "T", "E", "C"}

SHARD_RE = re.compile(r"wptreport-(\d+)\.json$")


def area_of(test):
    for area, prefixes in AREAS.items():
        if any(test.startswith(p) for p in prefixes):
            return area
    return None


def module_of(test):
    """CSS module of a test id: /css/<module>/... -> <module>, else None."""
    parts = test.split("?", 1)[0].split("/")
    if len(parts) > 3 and parts[1] == "css" and parts[2]:
        return parts[2]
    return None


def pct(pair):
    return round(100 * pair[0] / pair[1], 2) if pair[1] else None


# --- per-test maps: {test id: {"p": passed subtests, "n": subtests, "s": letter}}

def report_tests(results, into):
    for test in results:
        name = test.get("test", "")
        subs = test.get("subtests", []) or []
        into[name] = {
            "p": sum(1 for s in subs if s.get("status") == "PASS"),
            "n": len(subs),
            "s": STATUS_LETTER.get(test.get("status", ""), "?"),
        }
    return into


def load_fork_reports(paths):
    """Merge fork wptreport shards into one per-test map.

    Returns (tests, present shard ids). A report that is unreadable (a shard
    killed mid-write) or has no results is skipped: that shard is missing.
    """
    tests, present = {}, []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, ValueError) as e:
            print(f"skipping unreadable report {path}: {e}", file=sys.stderr)
            continue
        results = report.get("results") if isinstance(report, dict) else None
        if not results:
            print(f"skipping empty report {path}", file=sys.stderr)
            continue
        report_tests(results, tests)
        m = SHARD_RE.search(os.path.basename(path))
        if m:
            present.append(int(m.group(1)))
    return tests, sorted(present)


def missing_shards(expected, present):
    if not expected:
        return []
    have = set(present)
    return [i for i in range(1, expected + 1) if i not in have]


def fyi_tests(summary):
    """Per-test map from a wpt.fyi summary_v2 dict (or a raw wptreport)."""
    if isinstance(summary, list):
        return report_tests(summary, {})
    if isinstance(summary, dict) and isinstance(summary.get("results"), list):
        return report_tests(summary["results"], {})
    tests = {}
    for name, value in summary.items():
        if not isinstance(value, dict):
            continue
        c = value.get("c", [0, 0])
        tests[name] = {"p": c[0], "n": c[1], "s": value.get("s", "?")}
    return tests


# --- aggregation

def aggregate_areas(tests):
    t = {area: [0, 0] for area in AREAS}
    for name, r in tests.items():
        area = area_of(name)
        if area is not None:
            t[area][0] += r["p"]
            t[area][1] += r["n"]
    return t


def aggregate_modules(tests):
    mods = {}
    for name, r in tests.items():
        mod = module_of(name)
        if mod is None:
            continue
        m = mods.setdefault(mod, {"pass": 0, "total": 0, "tests": 0,
                                  "ref_pass": 0, "ref_total": 0})
        m["tests"] += 1
        m["pass"] += r["p"]
        m["total"] += r["n"]
        if r["n"] == 0 and r["s"] in COUNTED:
            m["ref_total"] += 1
            m["ref_pass"] += 1 if r["s"] == "P" else 0
    return mods


def css_total(mods):
    tot = {"pass": 0, "total": 0, "tests": 0, "ref_pass": 0, "ref_total": 0}
    for m in mods.values():
        for k in tot:
            tot[k] += m[k]
    return {"pass": tot["pass"], "total": tot["total"],
            "pct": pct((tot["pass"], tot["total"])), "tests": tot["tests"],
            "ref_pass": tot["ref_pass"], "ref_total": tot["ref_total"]}


def with_pct(m):
    if m is None:
        return None
    return dict(m, pct=pct((m["pass"], m["total"])))


def module_rows(fork, upstream, chrome):
    """One row per CSS module seen on any side, sorted by gap to Chrome.

    gap = Chrome passed subtests - fork passed subtests. Modules the fork
    did not run (no fork tests) have gap None and sort last.
    """
    rows = []
    for mod in set(fork) | set(upstream) | set(chrome):
        f = fork.get(mod)
        c = chrome.get(mod)
        gap = None
        if f is not None and f["tests"]:
            gap = (c["pass"] if c else 0) - f["pass"]
        rows.append({"module": mod, "fork": with_pct(f),
                     "upstream": with_pct(upstream.get(mod)),
                     "chrome": with_pct(c), "gap": gap})
    rows.sort(key=lambda r: (r["gap"] is None, -(r["gap"] or 0), r["module"]))
    return rows


def gap_list(fork, upstream, chrome, limit=GAP_LIMIT):
    """Top failing CSS tests where Chrome passes more subtests than the fork.

    Only tests the fork ran count (its tree can differ from wpt.fyi's).
    Ranked by per-test subtest gap, then grouped by module. Tests without
    subtests have no subtest gap; the ones Chrome passes and the fork fails
    are counted per module in no_subtest_failures instead.
    """
    cands, ref_fail = [], {}
    for name, fr in fork.items():
        mod = module_of(name)
        cr = chrome.get(name)
        if mod is None or cr is None:
            continue
        if fr["n"] == 0 and cr["n"] == 0:
            if cr["s"] == "P" and fr["s"] in COUNTED and fr["s"] != "P":
                ref_fail[mod] = ref_fail.get(mod, 0) + 1
            continue
        gap = cr["p"] - fr["p"]
        if gap <= 0:
            continue
        ur = upstream.get(name)
        cands.append({
            "test": name, "module": mod, "gap": gap,
            "fork": {"pass": fr["p"], "total": fr["n"]},
            "upstream": {"pass": ur["p"], "total": ur["n"]} if ur else None,
            "chrome": {"pass": cr["p"], "total": cr["n"]},
        })
    cands.sort(key=lambda t: (-t["gap"], t["test"]))
    groups = {}
    for t in cands[:limit]:
        g = groups.setdefault(t.pop("module"), {"gap": 0, "tests": []})
        g["gap"] += t["gap"]
        g["tests"].append(t)
    modules = [{"module": m, "gap": g["gap"], "tests": g["tests"]}
               for m, g in groups.items()]
    modules.sort(key=lambda m: (-m["gap"], m["module"]))
    return {"limit": limit, "candidates": len(cands), "modules": modules,
            "no_subtest_failures": dict(sorted(ref_fail.items()))}


# --- wpt.fyi

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


# --- output

def area_entry(t):
    return {
        area: {"pass": t[area][0], "total": t[area][1], "pct": pct(t[area])}
        for area in AREAS
    }


def run_meta(run):
    return {"run_id": run["id"], "version": run.get("browser_version", ""),
            "revision": run.get("revision", "")}


def build_data(date, fork_sha, fork, upstream, chrome, upstream_run,
               chrome_run, expected_shards=None, present_shards=()):
    mods = {side: aggregate_modules(t) for side, t in
            (("fork", fork), ("upstream", upstream), ("chrome", chrome))}
    runs = {
        "fork": {"sha": fork_sha},
        "upstream": run_meta(upstream_run),
        "chrome": run_meta(chrome_run),
    }
    for side, t in (("fork", fork), ("upstream", upstream), ("chrome", chrome)):
        runs[side]["areas"] = area_entry(aggregate_areas(t))
        runs[side]["css_total"] = css_total(mods[side])
    present = sorted(present_shards)
    return {
        "date": date,
        "fork_sha": fork_sha,
        "shards": {"expected": expected_shards, "present": present,
                   "missing": missing_shards(expected_shards, present)},
        "runs": runs,
        "css_modules": module_rows(mods["fork"], mods["upstream"], mods["chrome"]),
    }


def render_html(data, history):
    """Static tables: extra areas and CSS modules (fork vs upstream vs
    Chrome), plus the fork trend."""
    esc = html.escape
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

    def overall(side):
        a = runs[side]["areas"]
        return pct((sum(v["pass"] for v in a.values()),
                    sum(v["total"] for v in a.values())))

    f, u, c = overall("fork"), overall("upstream"), overall("chrome")

    def mcell(m):
        if m is None:
            return "not run"
        s = "n/a" if m["pct"] is None else f'{m["pct"]:.2f}%'
        return f'{s} ({m["pass"]}/{m["total"]})'

    def rcell(m):
        if m is None or not m["ref_total"]:
            return "&ndash;"
        return f'{m["ref_pass"]}/{m["ref_total"]}'

    mod_rows = "\n".join(
        f"<tr><td>{esc(r['module'])}</td><td>{mcell(r['fork'])}</td>"
        f"<td>{mcell(r['upstream'])}</td><td>{mcell(r['chrome'])}</td>"
        f"<td>{'n/a' if r['gap'] is None else r['gap']}</td>"
        f"<td>{rcell(r['fork'])}</td><td>{rcell(r['chrome'])}</td></tr>"
        for r in data.get("css_modules", [])
    )
    tot = {s: runs[s].get("css_total") for s in ("fork", "upstream", "chrome")}
    tot_gap = (tot["chrome"]["pass"] - tot["fork"]["pass"]
               if tot["fork"] and tot["chrome"] else "n/a")
    css_table = ""
    if data.get("css_modules"):
        css_table = f"""<h2>CSS modules</h2>
<p>Sorted by gap to Chrome in subtests (Chrome passed &minus; fork passed),
largest first. &ldquo;No-subtest&rdquo; columns count reftests and
crashtests by harness status (passed/total); they carry no subtests.</p>
<table><tr><th>module</th><th>fork</th><th>upstream</th><th>chrome</th>
<th>gap to chrome</th><th>fork no-subtest</th><th>chrome no-subtest</th></tr>
{mod_rows}
<tr><td><b>all CSS</b></td><td><b>{mcell(tot["fork"])}</b></td>
<td><b>{mcell(tot["upstream"])}</b></td><td><b>{mcell(tot["chrome"])}</b></td>
<td><b>{tot_gap}</b></td><td><b>{rcell(tot["fork"])}</b></td>
<td><b>{rcell(tot["chrome"])}</b></td></tr></table>"""

    shards = data.get("shards") or {}
    warn = ""
    if shards.get("missing"):
        warn = (f'<p class="warn"><b>Partial run.</b> Missing shards: '
                f'{", ".join(str(i) for i in shards["missing"])} of '
                f'{shards["expected"]}. Fork numbers cover only the shards '
                f'that produced reports.</p>')

    def show(v):
        return "n/a" if v is None else f"{v}%"

    def trend_line(h):
        line = (f"<li>{esc(h['date'])}: {show(h['fork_overall_pct'])} "
                f"(upstream {show(h['upstream_overall_pct'])}, "
                f"chrome {show(h['chrome_overall_pct'])})")
        if h.get("fork_css_pct") is not None:
            line += (f"; CSS {show(h['fork_css_pct'])} "
                     f"(chrome {show(h.get('chrome_css_pct'))})")
        return line + "</li>"

    trend = "\n".join(trend_line(h) for h in history[-14:])
    day = esc(data["date"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legatus Servo web-compat scoreboard</title>
<style>body{{font-family:system-ui,sans-serif;max-width:72rem;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;display:block;overflow-x:auto}}
td,th{{border:1px solid #999;padding:.3rem .6rem;text-align:right;white-space:nowrap}}
td:first-child,th:first-child{{text-align:left}}.warn{{background:#fff3cd;padding:.5rem}}</style></head><body>
<h1>Web-compat scoreboard ({day})</h1>
<p>Fork <code>{esc(runs["fork"]["sha"])}</code> vs upstream Servo
(<code>{esc(runs["upstream"].get("version", ""))}</code>) vs Chrome
(<code>{esc(runs["chrome"].get("version", ""))}</code>).
Pass rate = passed subtests / total subtests. Method: scoreboard/README.md.</p>
{warn}
<h2>Areas</h2>
<table><tr><th>area</th><th>fork</th><th>upstream</th><th>chrome</th>
<th>fork&minus;upstream</th><th>fork&minus;chrome</th></tr>
{rows}
<tr><td><b>overall</b></td><td><b>{show(f)}</b></td><td><b>{show(u)}</b></td>
<td><b>{show(c)}</b></td><td></td><td></td></tr></table>
{css_table}
<h2>Fork trend (overall %)</h2><ul>{trend}</ul>
<p>Daily JSON: <a href="data/{day}.json">data/{day}.json</a>;
gap list: <a href="data/{day}-gaps.json">data/{day}-gaps.json</a></p>
</body></html>
"""


def history_entry(data):
    def opct(side):
        a = data["runs"][side]["areas"]
        return pct((sum(v["pass"] for v in a.values()),
                    sum(v["total"] for v in a.values())))

    def cpct(side):
        t = data["runs"][side].get("css_total")
        return t["pct"] if t else None

    return {
        "date": data["date"],
        "fork_overall_pct": opct("fork"),
        "upstream_overall_pct": opct("upstream"),
        "chrome_overall_pct": opct("chrome"),
        "fork_css_pct": cpct("fork"),
        "chrome_css_pct": cpct("chrome"),
    }


def load_history(history_dir, date):
    history = []
    ddir = os.path.join(history_dir, "data") if history_dir else None
    if not ddir or not os.path.isdir(ddir):
        return history
    for name in sorted(os.listdir(ddir)):
        # Daily files only (YYYY-MM-DD.json), not gap lists.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", name) or name[:10] >= date:
            continue
        try:
            with open(os.path.join(ddir, name), encoding="utf-8") as f:
                history.append(history_entry(json.load(f)))
        except (OSError, ValueError, KeyError) as e:
            print(f"skipping history file {name}: {e}", file=sys.stderr)
    return history


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--fork-sha", required=True)
    ap.add_argument("--reports", nargs="+", required=True)
    ap.add_argument("--expected-shards", type=int, default=None)
    ap.add_argument("--history-dir", default=None)
    ap.add_argument("--out-data", required=True)
    ap.add_argument("--out-gaps", default=None)
    ap.add_argument("--out-html", required=True)
    args = ap.parse_args()

    fork, present = load_fork_reports(args.reports)
    if not fork:
        print("no usable fork reports", file=sys.stderr)
        return 1
    print(f"fork: shards {present}, {len(fork)} tests", flush=True)
    upstream_run = nearest_run("servo", args.date)
    chrome_run = nearest_run("chrome", args.date)
    print(f"upstream: servo run {upstream_run['id']} ({upstream_run.get('time_start','')[:10]})", flush=True)
    print(f"chrome: run {chrome_run['id']} ({chrome_run.get('time_start','')[:10]})", flush=True)
    upstream = fyi_tests(http_json(upstream_run["results_url"]))
    chrome = fyi_tests(http_json(chrome_run["results_url"]))

    data = build_data(args.date, args.fork_sha, fork, upstream, chrome,
                      upstream_run, chrome_run, args.expected_shards, present)
    if data["shards"]["missing"]:
        print(f"::warning::missing shards: {data['shards']['missing']}", flush=True)
    history = load_history(args.history_dir, args.date)
    history.append(history_entry(data))
    with open(args.out_data, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    if args.out_gaps:
        gaps = gap_list(fork, upstream, chrome)
        gaps = {"date": args.date, "fork_sha": args.fork_sha,
                "upstream_run": upstream_run["id"], "chrome_run": chrome_run["id"],
                "shards": data["shards"], **gaps}
        with open(args.out_gaps, "w", encoding="utf-8") as f:
            json.dump(gaps, f, indent=2)
    with open(args.out_html, "w", encoding="utf-8") as f:
        f.write(render_html(data, history))
    print(f"wrote {args.out_data}, {args.out_gaps or '(no gaps)'} and {args.out_html}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
