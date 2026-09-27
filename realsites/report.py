#!/usr/bin/env python3
"""Turn bench.py's raw runs into the published realsites data and page.

Writes data/realsites-<date>.json (validated against rs.schema), the page
realsites.html, and JPEG thumbnails of the worst sites (Servo, Chrome, and a
diff overlay with differing pixels in red).
"""

import argparse
import glob
import html
import json
import os
import sys
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rs import metrics, pixeldiff, schema  # noqa: E402

REPO = "legatus-ai/servo-engine"


def build_document(
    raw: dict,
    date: str,
    servo_meta: dict,
    chrome_version: str,
    diff_fn: Callable[[Optional[str], Optional[str]], Optional[float]],
    threshold: int,
) -> dict:
    sites = []
    for s in raw["sites"]:
        if s.get("status") != "measured":
            sites.append(
                {
                    "id": s["id"],
                    "category": s["category"],
                    "url": s.get("url"),
                    "status": "skipped",
                    "skip_reason": s.get("skip_reason") or "not measured",
                }
            )
            continue
        entry = {"id": s["id"], "category": s["category"], "url": s.get("url"), "status": "measured"}
        for b in ("servo", "chrome"):
            runs = s[b]["runs"]
            entry[b] = dict(metrics.aggregate_browser(runs), runs=runs)
        shots = s.get("shots") or {}
        entry["load_ratio"] = metrics.ratio(entry["servo"]["load_ms"], entry["chrome"]["load_ms"])
        entry["visual_diff_pct"] = diff_fn(shots.get("servo"), shots.get("chrome"))
        entry["thumbs"] = None
        sites.append(entry)
    config = dict(raw["config"], diff_threshold=threshold)
    return {
        "schema": schema.SCHEMA_ID,
        "date": date,
        "servo": {
            "version": raw.get("servo_version"),
            "build_run_id": servo_meta.get("build_run_id"),
            "artifact_created_at": servo_meta.get("artifact_created_at"),
            "legatus_sha": servo_meta.get("legatus_sha"),
        },
        "chrome": {"version": raw.get("chrome_version") or chrome_version},
        "config": config,
        "headline": metrics.headline(sites),
        "sites": sites,
    }


# --- HTML ---

E = html.escape


def fmt_ms(v: Optional[float]) -> str:
    return "&ndash;" if v is None else f"{v:.0f}"


def fmt_pct(v: Optional[float]) -> str:
    return "&ndash;" if v is None else f"{v:.1f}%"


def fmt_ratio(v: Optional[float]) -> str:
    return "&ndash;" if v is None else f"{v:.2f}&times;"


def fmt_rate(v: Optional[float]) -> str:
    return "&ndash;" if v is None else f"{100 * v:.1f}%"


def status_cell(b: dict) -> str:
    st = b["status"]
    if st == "ok":
        return '<td class="ok">ok</td>'
    runs = len(b.get("runs") or [])
    counts = []
    if b.get("crashes"):
        counts.append(f"{b['crashes']}/{runs} crash")
    if b.get("hangs"):
        counts.append(f"{b['hangs']}/{runs} hang")
    label = ", ".join(counts) or st
    detail = b.get("panic") or next((r.get("detail") for r in b.get("runs", []) if r.get("detail")), "")
    tip = f"<div class=detail>{E(detail)}</div>" if detail else ""
    return f'<td class="bad">{E(label)}{tip}</td>'


STYLE = """
:root{--fg:#1b1b1f;--muted:#5d5d66;--bg:#fff;--line:#d6d6de;--ok:#0a7a3e;--bad:#b3261e;--card:#f5f5f8}
@media (prefers-color-scheme:dark){:root{--fg:#e7e7ec;--muted:#a3a3ad;--bg:#141417;--line:#34343c;--ok:#5fd08e;--bad:#ff8a80;--card:#1d1d22}}
body{font-family:system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:72rem;margin:2rem auto;padding:0 1rem;line-height:1.45}
a{color:inherit}
nav{margin-bottom:1rem;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.75rem;margin:1rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:.75rem 1rem}
.card b{display:block;font-size:1.6rem}
.card span{color:var(--muted);font-size:.85rem}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.9rem}
td,th{border-bottom:1px solid var(--line);padding:.35rem .5rem;text-align:right;vertical-align:top}
td:first-child,th:first-child,td.l,th.l{text-align:left}
td.ok{color:var(--ok)}td.bad{color:var(--bad)}
.detail{font-size:.75rem;color:var(--muted);max-width:26rem;text-align:left;word-break:break-word}
.gallery{display:grid;gap:1.25rem}
.gallery figure{margin:0}
.gallery .row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.5rem}
.gallery img{width:100%;height:auto;border:1px solid var(--line)}
.gallery figcaption{font-size:.85rem;color:var(--muted);margin-bottom:.35rem}
p.method{color:var(--muted);font-size:.85rem}
"""


def render_html(doc: dict, history: List[dict], thumbs: Dict[str, dict]) -> str:
    head = doc["headline"]
    date = doc["date"]
    servo = doc["servo"]
    sha = servo.get("legatus_sha") or "unknown"
    run_id = servo.get("build_run_id")
    build = (
        f'<a href="https://github.com/{REPO}/actions/runs/{run_id}">build run {run_id}</a>' if run_id else "unknown build"
    )
    out = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Servo vs Chrome: real sites</title><style>{STYLE}</style></head><body>",
        '<nav><a href="index.html">WPT scoreboard</a> &middot; <b>Real-site benchmark</b></nav>',
        f"<h1>Real-site benchmark ({E(date)})</h1>",
        f"<p>Legatus Servo fork <code>{E(sha[:12])}</code> ({E(servo.get('version') or '?')}, {build})"
        f" vs headless {E(doc['chrome']['version'])}. {head['sites']} sites measured"
        f"{f', {head['skipped']} skipped' if head.get('skipped') else ''};"
        f" median of {doc['config']['runs']} cold runs each.</p>",
        '<div class="cards">',
        f"<div class=card><b>{fmt_ratio(head['load_ratio_median'])}</b><span>Servo/Chrome load time, median across sites (lower is better)</span></div>",
        f"<div class=card><b>{fmt_rate(head['servo_crash_rate'])}</b><span>Servo crash rate ({head['servo_crash_sites']}/{head['sites']} sites crashed in at least one run)</span></div>",
        f"<div class=card><b>{fmt_rate(head['servo_hang_rate'])}</b><span>Servo hang rate ({head['servo_hang_sites']}/{head['sites']} sites, no load in {doc['config']['hang_timeout_s']} s)</span></div>",
        f"<div class=card><b>{fmt_pct(head['visual_diff_median'])}</b><span>Median visual diff vs Chrome (pixels differing at 1280&times;800)</span></div>",
        "</div>",
        "<h2>Per site</h2><div class=wrap><table>",
        '<tr><th class="l">site</th><th class="l">category</th><th>Servo load ms</th><th>Chrome load ms</th>'
        "<th>ratio</th><th>Servo first paint ms</th><th>Chrome first paint ms</th>"
        '<th class="l">Servo</th><th class="l">Chrome</th><th>visual diff</th></tr>',
    ]
    for s in doc["sites"]:
        name = E(s["id"])
        if s.get("url"):
            name = f'<a href="{E(s["url"])}">{name}</a>'
        if s["status"] == "skipped":
            out.append(
                f'<tr><td>{name}</td><td class="l">{E(s["category"])}</td>'
                f'<td colspan="8" class="l">skipped: {E(s["skip_reason"])}</td></tr>'
            )
            continue
        sv, ch = s["servo"], s["chrome"]
        out.append(
            f'<tr><td>{name}</td><td class="l">{E(s["category"])}</td>'
            f"<td>{fmt_ms(sv['load_ms'])}</td><td>{fmt_ms(ch['load_ms'])}</td><td>{fmt_ratio(s.get('load_ratio'))}</td>"
            f"<td>{fmt_ms(sv['first_paint_ms'])}</td><td>{fmt_ms(ch['first_paint_ms'])}</td>"
            f"{status_cell(sv)}{status_cell(ch)}<td>{fmt_pct(s['visual_diff_pct'])}</td></tr>"
        )
    out.append("</table></div>")

    worst = metrics.worst(doc["sites"], 10)
    if worst:
        out.append("<h2>Worst 10</h2><p class=method>Servo crashes first, then the largest visual diffs."
                   " Each row: Servo, Chrome, and Chrome in gray with differing pixels in red.</p><div class=gallery>")
        for s in worst:
            t = thumbs.get(s["id"])
            cap = f"{E(s['id'])}: servo {E(s['servo']['status'])}, diff {fmt_pct(s['visual_diff_pct'])}"
            if s["servo"].get("panic"):
                cap += f" &middot; {E(s['servo']['panic'])}"
            if t:
                imgs = "".join(
                    f'<img loading="lazy" alt="{E(s["id"])} {k}" src="{E(t[k])}">' for k in ("servo", "chrome", "diff")
                )
                out.append(f"<figure><figcaption>{cap}</figcaption><div class=row>{imgs}</div></figure>")
            else:
                out.append(f"<figure><figcaption>{cap} (no Servo screenshot)</figcaption></figure>")
        out.append("</div>")

    if history:
        out.append("<h2>Trend</h2><div class=wrap><table><tr><th class=l>date</th><th>load ratio</th>"
                   "<th>crash rate</th><th>hang rate</th><th>median visual diff</th><th>sites</th></tr>")
        for h in sorted(history + [{"date": date, "headline": head}], key=lambda x: x["date"])[-30:]:
            hh = h["headline"]
            out.append(
                f"<tr><td>{E(h['date'])}</td><td>{fmt_ratio(hh.get('load_ratio_median'))}</td>"
                f"<td>{fmt_rate(hh.get('servo_crash_rate'))}</td><td>{fmt_rate(hh.get('servo_hang_rate'))}</td>"
                f"<td>{fmt_pct(hh.get('visual_diff_median'))}</td><td>{hh.get('sites', '')}</td></tr>"
            )
        out.append("</table></div>")

    out.append(
        f'<p>Daily JSON: <a href="data/realsites-{E(date)}.json">data/realsites-{E(date)}.json</a></p>'
        "<p class=method>Method: each site is a pinned snapshot served from localhost with no network."
        " Every run is a fresh browser process with an empty profile, driven over WebDriver at 1280&times;800,"
        " device pixel ratio 1. Load = the page's own loadEventStart (Navigation Timing); first paint = Paint Timing"
        " (first-paint, else first-contentful-paint) when the engine reports it. Screenshot 2 s after load."
        " A crash is a non-zero exit, a panic, or a WebDriver report of a dead page; a hang is no load event in"
        f" {doc['config']['hang_timeout_s']} s. A pixel differs when any channel differs by more than"
        f" {doc['config']['diff_threshold']}/255. Source: realsites/README.md.</p>"
        "</body></html>"
    )
    return "\n".join(out)


def load_history(history_dir: str, date: str) -> List[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(history_dir, "realsites-*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if d.get("date") and d["date"] != date and isinstance(d.get("headline"), dict):
            out.append({"date": d["date"], "headline": d["headline"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", required=True, help="bench.py --out directory")
    ap.add_argument("--date", required=True)
    ap.add_argument("--servo-meta", required=True, help="JSON with build_run_id, artifact_created_at, legatus_sha")
    ap.add_argument("--history-dir", default="")
    ap.add_argument("--out-dir", required=True, help="site root: gets data/, realsites.html, realsites-thumbs/")
    ap.add_argument("--threshold", type=int, default=pixeldiff.DEFAULT_THRESHOLD)
    args = ap.parse_args()

    with open(os.path.join(args.raw_dir, "raw.json"), encoding="utf-8") as f:
        raw = json.load(f)
    with open(args.servo_meta, encoding="utf-8") as f:
        meta = json.load(f)
    w, h = raw["config"]["viewport"]

    def diff(servo_png, chrome_png):
        if not servo_png or not chrome_png:
            return None
        a = pixeldiff.load_rgb(os.path.join(args.raw_dir, servo_png), w, h)
        b = pixeldiff.load_rgb(os.path.join(args.raw_dir, chrome_png), w, h)
        return pixeldiff.diff_percent(a, b, w, h, args.threshold)

    doc = build_document(raw, args.date, meta, "unknown", diff, args.threshold)

    thumbs_dir = os.path.join(args.out_dir, "realsites-thumbs")
    os.makedirs(thumbs_dir, exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "data"), exist_ok=True)
    shots = {s["id"]: s.get("shots") or {} for s in raw["sites"]}
    thumbs = {}
    for s in metrics.worst(doc["sites"], 10):
        sh = shots.get(s["id"], {})
        if sh.get("servo") and sh.get("chrome"):
            names = pixeldiff.write_thumbs(
                os.path.join(args.raw_dir, sh["servo"]),
                os.path.join(args.raw_dir, sh["chrome"]),
                os.path.join(thumbs_dir, s["id"]),
                w,
                h,
                args.threshold,
            )
            rel = {k: os.path.relpath(v, args.out_dir).replace(os.sep, "/") for k, v in names.items()}
            thumbs[s["id"]] = rel
            s["thumbs"] = rel

    errors = schema.validate(doc)
    if errors:
        print("realsites document failed validation:", *errors, sep="\n  ", file=sys.stderr)
        return 1
    history = load_history(args.history_dir, args.date) if args.history_dir else []
    with open(os.path.join(args.out_dir, "data", f"realsites-{args.date}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    with open(os.path.join(args.out_dir, "realsites.html"), "w", encoding="utf-8") as f:
        f.write(render_html(doc, history, thumbs))
    head = doc["headline"]
    print(
        f"sites={head['sites']} skipped={head['skipped']} load_ratio_median={head['load_ratio_median']}"
        f" crash_rate={head['servo_crash_rate']} hang_rate={head['servo_hang_rate']}"
        f" visual_diff_median={head['visual_diff_median']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
