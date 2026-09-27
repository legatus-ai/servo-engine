#!/usr/bin/env python3
"""Capture the pinned snapshots with SingleFile (runs in CI, never locally).

For every snapshot site in sites.json, saves the live page as one
self-contained HTML file (CSS, images and fonts inlined) with the pinned
Chrome, at 1280x800. Sites marked "scripts": true keep their scripts (and
hidden elements, which scripts may show later); the others are saved as
rendered, with scripts removed.

Writes <out>/<id>.html and <out>/MANIFEST.json (source URL, capture time,
size, SHA-256, tool versions). Pages over --max-page-mb are dropped and
reported, and the run fails if the kept total exceeds --max-total-mb.
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", default=os.path.join(here, "sites.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--single-file", required=True, help="path to the single-file CLI")
    ap.add_argument("--chrome", required=True)
    ap.add_argument("--chrome-version", required=True)
    ap.add_argument("--single-file-version", required=True)
    ap.add_argument("--max-page-mb", type=float, default=4.0)
    ap.add_argument("--max-total-mb", type=float, default=48.0)
    ap.add_argument("--only", default="", help="comma-separated site ids (default: all)")
    args = ap.parse_args()

    with open(args.sites, encoding="utf-8") as f:
        sites = [s for s in json.load(f)["sites"] if s.get("source", "snapshot") == "snapshot"]
    only = {s for s in args.only.split(",") if s}
    if only:
        sites = [s for s in sites if s["id"] in only]
    os.makedirs(args.out, exist_ok=True)

    manifest = {
        "captured_with": {"chrome": args.chrome_version, "single-file-cli": args.single_file_version},
        "viewport": [1280, 800],
        "sites": {},
    }
    failures = []
    total = 0
    for s in sites:
        out = os.path.join(args.out, f"{s['id']}.html")
        scripts = bool(s.get("scripts"))
        cmd = [
            args.single_file,
            s["url"],
            out,
            f"--browser-executable-path={args.chrome}",
            "--browser-width=1280",
            "--browser-height=800",
            "--browser-arg=--no-sandbox",
            "--browser-arg=--hide-scrollbars",
            "--browser-load-max-time=90000",
            "--browser-wait-until=networkIdle",
            "--max-resource-size-enabled=true",
            "--max-resource-size=1",
            "--filename-conflict-action=overwrite",
            f"--block-scripts={'false' if scripts else 'true'}",
            f"--remove-hidden-elements={'false' if scripts else 'true'}",
        ]
        print(f"capture {s['id']}: {s['url']}", flush=True)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            err = (res.stderr or res.stdout).strip()[-500:] if res.returncode else ""
        except subprocess.TimeoutExpired:
            err = "timed out after 240 s"
        if err or not os.path.exists(out) or os.path.getsize(out) < 512:
            failures.append(f"{s['id']}: {err or 'no output'}")
            if os.path.exists(out):
                os.remove(out)
            continue
        size = os.path.getsize(out)
        if size > args.max_page_mb * 1024 * 1024:
            failures.append(f"{s['id']}: {size / 1048576:.1f} MB exceeds {args.max_page_mb} MB, dropped")
            os.remove(out)
            continue
        with open(out, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        total += size
        manifest["sites"][s["id"]] = {
            "url": s["url"],
            "captured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bytes": size,
            "sha256": digest,
            "scripts": scripts,
        }
        print(f"  ok: {size / 1048576:.2f} MB", flush=True)

    manifest["total_bytes"] = total
    with open(os.path.join(args.out, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print(f"captured {len(manifest['sites'])}/{len(sites)} pages, {total / 1048576:.1f} MB total")
    for line in failures:
        print(f"::warning::capture failed: {line}")
    if total > args.max_total_mb * 1024 * 1024:
        print(f"::error::total {total / 1048576:.1f} MB exceeds {args.max_total_mb} MB")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
