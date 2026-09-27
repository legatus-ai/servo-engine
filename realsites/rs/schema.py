"""The realsites JSON contracts, checked without third-party dependencies.

`validate` checks a published nightly document (data/realsites-<date>.json).
`validate_sites` checks the committed site list (realsites/sites.json).
Both return a list of human-readable errors; empty means valid.
"""

import re
from typing import Any, List

SCHEMA_ID = "legatus-servo/realsites/v1"
RUN_STATUSES = {"ok", "crash", "hang", "error"}
SITE_STATUSES = {"measured", "skipped"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _opt_num(errors: List[str], path: str, v: Any, lo: float = 0.0, hi: float = float("inf")) -> None:
    if v is None:
        return
    if not _is_num(v):
        errors.append(f"{path}: expected a number or null, got {type(v).__name__}")
    elif not lo <= v <= hi:
        errors.append(f"{path}: {v} outside [{lo}, {hi}]")


def _require(errors: List[str], path: str, obj: Any, keys: List[str]) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{path}: expected an object")
        return False
    ok = True
    for k in keys:
        if k not in obj:
            errors.append(f"missing key: {path + '.' if path else ''}{k}")
            ok = False
    return ok


def _browser(errors: List[str], path: str, b: Any) -> None:
    if not _require(errors, path, b, ["status", "load_ms", "first_paint_ms", "panic", "runs"]):
        return
    if b["status"] not in RUN_STATUSES:
        errors.append(f"{path}.status: {b['status']!r} not in {sorted(RUN_STATUSES)}")
    _opt_num(errors, f"{path}.load_ms", b["load_ms"])
    _opt_num(errors, f"{path}.first_paint_ms", b["first_paint_ms"])
    if not isinstance(b["runs"], list) or not b["runs"]:
        errors.append(f"{path}.runs: expected a non-empty list")
        return
    for i, r in enumerate(b["runs"]):
        rp = f"{path}.runs[{i}]"
        if not _require(errors, rp, r, ["status", "load_ms"]):
            continue
        if r["status"] not in RUN_STATUSES:
            errors.append(f"{rp}.status: {r['status']!r} not in {sorted(RUN_STATUSES)}")
        _opt_num(errors, f"{rp}.load_ms", r["load_ms"])
        _opt_num(errors, f"{rp}.first_paint_ms", r.get("first_paint_ms"))
        _opt_num(errors, f"{rp}.nav_ms", r.get("nav_ms"))


def validate(doc: Any) -> List[str]:
    errors: List[str] = []
    if not _require(errors, "", doc, ["schema", "date", "servo", "chrome", "config", "headline", "sites"]):
        return errors
    if doc["schema"] != SCHEMA_ID:
        errors.append(f"schema: expected {SCHEMA_ID!r}, got {doc['schema']!r}")
    if not isinstance(doc["date"], str) or not _DATE.match(doc["date"]):
        errors.append(f"date: expected YYYY-MM-DD, got {doc['date']!r}")
    _require(errors, "servo", doc["servo"], ["version", "build_run_id", "legatus_sha"])
    _require(errors, "chrome", doc["chrome"], ["version"])
    _require(errors, "config", doc["config"], ["runs", "viewport", "hang_timeout_s", "settle_s", "diff_threshold"])

    head = doc["headline"]
    if _require(
        errors,
        "headline",
        head,
        ["sites", "servo_crash_rate", "servo_hang_rate", "load_ratio_median", "visual_diff_median"],
    ):
        _opt_num(errors, "headline.servo_crash_rate", head["servo_crash_rate"], 0.0, 1.0)
        _opt_num(errors, "headline.servo_hang_rate", head["servo_hang_rate"], 0.0, 1.0)
        _opt_num(errors, "headline.load_ratio_median", head["load_ratio_median"])
        _opt_num(errors, "headline.visual_diff_median", head["visual_diff_median"], 0.0, 100.0)

    if not isinstance(doc["sites"], list):
        errors.append("sites: expected a list")
        return errors
    seen = set()
    for i, s in enumerate(doc["sites"]):
        sp = f"sites[{i}]"
        if not _require(errors, sp, s, ["id", "category", "status"]):
            continue
        if s["id"] in seen:
            errors.append(f"{sp}.id: duplicate site id {s['id']!r}")
        seen.add(s["id"])
        if s["status"] not in SITE_STATUSES:
            errors.append(f"{sp}.status: {s['status']!r} not in {sorted(SITE_STATUSES)}")
            continue
        if s["status"] == "skipped":
            if not s.get("skip_reason"):
                errors.append(f"{sp}.skip_reason: required for a skipped site")
            continue
        if not _require(errors, sp, s, ["servo", "chrome", "visual_diff_pct"]):
            continue
        _browser(errors, f"{sp}.servo", s["servo"])
        _browser(errors, f"{sp}.chrome", s["chrome"])
        _opt_num(errors, f"{sp}.visual_diff_pct", s["visual_diff_pct"], 0.0, 100.0)
        _opt_num(errors, f"{sp}.load_ratio", s.get("load_ratio"))
    return errors


def validate_sites(doc: Any) -> List[str]:
    """Check the committed site list."""
    errors: List[str] = []
    if not _require(errors, "", doc, ["version", "sites"]):
        return errors
    if not isinstance(doc["sites"], list) or not doc["sites"]:
        return errors + ["sites: expected a non-empty list"]
    seen = set()
    for i, s in enumerate(doc["sites"]):
        sp = f"sites[{i}]"
        if not _require(errors, sp, s, ["id", "category", "license"]):
            continue
        if not isinstance(s["id"], str) or not _SITE_ID.match(s["id"]):
            errors.append(f"{sp}.id: {s['id']!r} must match {_SITE_ID.pattern}")
        if s["id"] in seen:
            errors.append(f"{sp}.id: duplicate site id {s['id']!r}")
        seen.add(s["id"])
        source = s.get("source", "snapshot")
        if source not in ("snapshot", "pane"):
            errors.append(f"{sp}.source: {source!r} must be 'snapshot' or 'pane'")
        if source == "snapshot" and not str(s.get("url", "")).startswith("https://"):
            errors.append(f"{sp}.url: a snapshot site needs its https:// source URL")
        if not isinstance(s.get("scripts", False), bool):
            errors.append(f"{sp}.scripts: expected true or false")
    return errors
