#!/usr/bin/env python3
"""Run the real-site benchmark: every site, N cold runs each, Servo and Chrome.

Each run starts a fresh browser process with a fresh, empty profile, drives
it over W3C WebDriver (servoshell --webdriver / chromedriver), navigates to
the locally served snapshot, waits for the load event (hang after
--hang-timeout seconds), waits --settle seconds, reads the page's own
Navigation Timing and Paint Timing entries, and takes a viewport screenshot.

Output: <out>/raw.json with every run, and <out>/shots/<site>.<browser>.png.
report.py turns that into the published data and page.
"""

import argparse
import functools
import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rs import classify  # noqa: E402
from rs.webdriver import Session, WebDriverError  # noqa: E402

TIMING_JS = """
var out = {load: null, fp: null, fcp: null, src: null};
try {
  var n = performance.getEntriesByType('navigation');
  if (n && n.length && n[0].loadEventStart > 0) { out.load = n[0].loadEventStart; out.src = 'navigation-timing-2'; }
} catch (e) {}
if (out.load === null) {
  try {
    var t = performance.timing;
    if (t && t.loadEventStart > 0) { out.load = t.loadEventStart - t.navigationStart; out.src = 'navigation-timing-1'; }
  } catch (e) {}
}
try {
  performance.getEntriesByType('paint').forEach(function (e) {
    if (e.name === 'first-paint') out.fp = e.startTime;
    if (e.name === 'first-contentful-paint') out.fcp = e.startTime;
  });
} catch (e) {}
return out;
"""

STDERR_TAIL = 256 * 1024


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the job log readable
        pass


def serve(directory: str, port: int) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a browser (or driver) and everything it spawned."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def read_tail(path: str) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - STDERR_TAIL))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Browser:
    name = ""

    def __init__(self, args):
        self.args = args

    def launch(self, port: int, profile: str, log) -> subprocess.Popen:
        raise NotImplementedError

    def capabilities(self, profile: str) -> dict:
        return {}

    # Servo's own exit status is meaningful; chromedriver's is not (Chrome
    # crashes surface as WebDriver errors instead).
    process_is_browser = False


class Servo(Browser):
    name = "servo"
    process_is_browser = True

    def launch(self, port, profile, log):
        w, h = self.args.viewport
        cmd = [
            self.args.servo,
            "--headless",
            "--hard-fail",
            f"--webdriver={port}",
            "--window-size",
            f"{w}x{h}",
            "--device-pixel-ratio",
            "1",
            "--config-dir",
            profile,
            "--temporary-storage",
            "about:blank",
        ]
        return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def version(self) -> str:
        out = subprocess.run([self.args.servo, "--version"], capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else "unknown"


class Chrome(Browser):
    name = "chrome"

    def launch(self, port, profile, log):
        cmd = [self.args.chromedriver, f"--port={port}"]
        return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def capabilities(self, profile):
        w, h = self.args.viewport
        return {
            "browserName": "chrome",
            "goog:chromeOptions": {
                "binary": self.args.chrome,
                "args": [
                    "--headless=new",
                    f"--window-size={w},{h}",
                    "--force-device-scale-factor=1",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-sandbox",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--metrics-recording-only",
                ],
            },
        }

    def version(self) -> str:
        out = subprocess.run([self.args.chrome, "--version"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or "unknown"


def one_run(browser: Browser, url: str, shot_path: Optional[str], args) -> dict:
    profile = tempfile.mkdtemp(prefix=f"rs-{browser.name}-")
    log_path = os.path.join(profile, "browser.log")
    port = free_port()
    webdriver_error = None
    timed_out = False
    nav_ms = None
    timings = None
    shot = None
    with open(log_path, "wb") as log:
        proc = browser.launch(port, profile, log)
        session = Session(f"http://127.0.0.1:{port}", http_timeout=30)
        try:
            session.wait_ready(30)
            session.start(browser.capabilities(profile))
            session.set_timeouts(page_load_ms=args.hang_timeout * 1000, script_ms=10000)
            t0 = time.monotonic()
            # The HTTP timeout sits above the page-load timeout, so a browser
            # that stops answering entirely is still caught as a hang.
            session.navigate(url, timeout=args.hang_timeout + 15)
            nav_ms = (time.monotonic() - t0) * 1000.0
            time.sleep(args.settle)
            try:
                timings = session.execute(TIMING_JS)
            except WebDriverError as e:
                print(f"    timing script failed: {e}", flush=True)
            shot = session.screenshot()
        except WebDriverError as e:
            webdriver_error = str(e)
            timed_out = e.timed_out
        exit_code = proc.poll()
        if exit_code is None and webdriver_error and not timed_out:
            # A crash shows up as a refused connection a moment before the
            # process is reaped; give it that moment.
            try:
                exit_code = proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                exit_code = None
        session.quit()
        kill_tree(proc)
    stderr = read_tail(log_path)
    shutil.rmtree(profile, ignore_errors=True)

    status, detail = classify.classify_run(
        exit_code=exit_code if browser.process_is_browser else None,
        timed_out=timed_out,
        stderr=stderr if browser.process_is_browser else "",
        webdriver_error=webdriver_error,
        hang_timeout_s=args.hang_timeout,
    )
    load_ms = first_paint = None
    load_source = None
    if status == "ok":
        if timings and isinstance(timings, dict):
            load_ms = timings.get("load")
            first_paint = timings.get("fp") if timings.get("fp") is not None else timings.get("fcp")
            load_source = timings.get("src")
        if load_ms is None and nav_ms is not None:
            load_ms, load_source = nav_ms, "webdriver-navigate"
        if shot and shot_path:
            with open(shot_path, "wb") as f:
                f.write(shot)
    return {
        "status": status,
        "load_ms": round(load_ms, 1) if load_ms is not None else None,
        "first_paint_ms": round(first_paint, 1) if first_paint is not None else None,
        "nav_ms": round(nav_ms, 1) if nav_ms is not None else None,
        "load_source": load_source,
        "detail": detail,
    }


def snapshot_path(site: dict, snapshots: str) -> str:
    if site.get("source") == "pane":
        return os.path.join(snapshots, "pane", "index.html")
    return os.path.join(snapshots, f"{site['id']}.html")


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", default=os.path.join(here, "sites.json"))
    ap.add_argument("--snapshots", default=os.path.join(here, "snapshots"))
    ap.add_argument("--servo", required=True, help="path to servoshell")
    ap.add_argument("--chrome", required=True, help="path to the pinned Chrome binary")
    ap.add_argument("--chromedriver", required=True, help="path to the matching chromedriver")
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--hang-timeout", type=int, default=60)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--only", default="", help="comma-separated site ids (default: all)")
    args = ap.parse_args()
    args.viewport = (1280, 800)

    with open(args.sites, encoding="utf-8") as f:
        sites = json.load(f)["sites"]
    only = {s for s in args.only.split(",") if s}
    if only:
        sites = [s for s in sites if s["id"] in only]

    os.makedirs(os.path.join(args.out, "shots"), exist_ok=True)
    port = free_port()
    server = serve(args.snapshots, port)
    browsers = [Servo(args), Chrome(args)]
    raw = {
        "servo_version": browsers[0].version(),
        "chrome_version": browsers[1].version(),
        "config": {
            "runs": args.runs,
            "viewport": list(args.viewport),
            "hang_timeout_s": args.hang_timeout,
            "settle_s": args.settle,
        },
        "sites": [],
    }
    print(f"servo: {raw['servo_version']}\nchrome: {raw['chrome_version']}", flush=True)

    # Warm the OS file cache for both binaries so run 1 is not a disk benchmark.
    warm = os.path.join(args.snapshots, "..", "warmup.html")
    if os.path.exists(warm):
        shutil.copy(warm, os.path.join(args.snapshots, "__warmup.html"))
        for b in browsers:
            r = one_run(b, f"http://127.0.0.1:{port}/__warmup.html", None, args)
            print(f"warm-up {b.name}: {r['status']} {r['detail'] or ''}", flush=True)

    for i, site in enumerate(sites, 1):
        entry = {"id": site["id"], "category": site["category"], "url": site.get("url")}
        path = snapshot_path(site, args.snapshots)
        if not os.path.exists(path):
            reason = (
                "private pane bundle not available to this run"
                if site.get("source") == "pane"
                else "snapshot not captured yet"
            )
            entry.update(status="skipped", skip_reason=reason)
            raw["sites"].append(entry)
            print(f"[{i}/{len(sites)}] {site['id']}: skipped ({reason})", flush=True)
            continue
        rel = os.path.relpath(path, args.snapshots).replace(os.sep, "/")
        url = f"http://127.0.0.1:{port}/{rel}"
        entry["status"] = "measured"
        entry["shots"] = {}
        for b in browsers:
            entry[b.name] = {"runs": []}
        for run in range(1, args.runs + 1):
            for b in browsers:
                shot = os.path.join(args.out, "shots", f"{site['id']}.{b.name}.png")
                r = one_run(b, url, shot, args)
                entry[b.name]["runs"].append(r)
                if r["status"] == "ok" and os.path.exists(shot):
                    entry["shots"][b.name] = os.path.relpath(shot, args.out).replace(os.sep, "/")
                print(
                    f"[{i}/{len(sites)}] {site['id']} {b.name} run {run}: {r['status']}"
                    f" load={r['load_ms']} fp={r['first_paint_ms']} {r['detail'] or ''}",
                    flush=True,
                )
        raw["sites"].append(entry)
        # Written after every site so a job timeout still leaves partial data.
        with open(os.path.join(args.out, "raw.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)

    with open(os.path.join(args.out, "raw.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=1)
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
