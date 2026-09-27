"""Pure aggregation: medians over runs, per-site status, and the headline numbers."""

from typing import Iterable, List, Optional

# Worst first: a site's status is the worst status of any of its runs.
STATUS_RANK = {"crash": 3, "hang": 2, "error": 1, "ok": 0}


def median(values: Iterable[Optional[float]]) -> Optional[float]:
    """Median of the non-missing values, or None when there are none."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2


def ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def aggregate_browser(runs: List[dict]) -> dict:
    """Fold one browser's runs on one site into its reported numbers.

    Load and paint medians use only the runs that produced a number, so a
    single hang does not erase the timing of the two runs that loaded; the
    status still reports the hang.
    """
    if not runs:
        return {
            "status": "error",
            "load_ms": None,
            "first_paint_ms": None,
            "panic": None,
            "crashes": 0,
            "hangs": 0,
        }
    status = max((r["status"] for r in runs), key=lambda s: STATUS_RANK[s])
    panic = next((r.get("detail") for r in runs if r["status"] == "crash" and r.get("detail")), None)
    return {
        "status": status,
        "load_ms": median(r.get("load_ms") for r in runs),
        "first_paint_ms": median(r.get("first_paint_ms") for r in runs),
        "panic": panic,
        "crashes": sum(1 for r in runs if r["status"] == "crash"),
        "hangs": sum(1 for r in runs if r["status"] == "hang"),
    }


def _rate(count: int, total: int) -> Optional[float]:
    return count / total if total else None


def headline(sites: List[dict]) -> dict:
    """Headline numbers across the measured sites (skipped sites are counted apart)."""
    measured = [s for s in sites if s.get("status") == "measured"]
    n = len(measured)
    crash = sum(1 for s in measured if s["servo"]["status"] == "crash")
    hang = sum(1 for s in measured if s["servo"]["status"] == "hang")
    chrome_fail = sum(1 for s in measured if s["chrome"]["status"] != "ok")
    ratios = [ratio(s["servo"].get("load_ms"), s["chrome"].get("load_ms")) for s in measured]
    return {
        "sites": n,
        "skipped": len(sites) - n,
        "servo_crash_sites": crash,
        "servo_hang_sites": hang,
        "servo_crash_rate": _rate(crash, n),
        "servo_hang_rate": _rate(hang, n),
        "load_ratio_median": median(ratios),
        "visual_diff_median": median(s.get("visual_diff_pct") for s in measured),
        "chrome_failure_sites": chrome_fail,
    }


def worst(sites: List[dict], count: int) -> List[dict]:
    """The `count` worst measured sites: Servo crashes first, then by visual diff."""
    measured = [s for s in sites if s.get("status") == "measured"]

    def key(s):
        failed = s["servo"]["status"] == "crash"
        return (0 if failed else 1, -(s.get("visual_diff_pct") or 0.0), s["id"])

    return sorted(measured, key=key)[:count]
