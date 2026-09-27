"""Unit tests for rs.schema: the published realsites JSON contract."""

import copy
import json
import os
import unittest

from rs import schema

HERE = os.path.dirname(os.path.abspath(__file__))


def browser(status="ok", load=120.5):
    return {
        "status": status,
        "load_ms": load,
        "first_paint_ms": 40.0,
        "panic": None,
        "crashes": 0,
        "hangs": 0,
        "runs": [
            {"status": status, "load_ms": load, "first_paint_ms": 40.0, "nav_ms": 150.0, "detail": None}
        ],
    }


def valid_doc():
    return {
        "schema": schema.SCHEMA_ID,
        "date": "2026-09-27",
        "servo": {
            "version": "Servo 0.1.0-abc",
            "build_run_id": 36280908230,
            "artifact_created_at": "2026-09-27T00:10:27Z",
            "legatus_sha": "4cfa8189adba49de3f48c5b534568c19c49313e4",
        },
        "chrome": {"version": "154.0.8037.57"},
        "config": {
            "runs": 3,
            "viewport": [1280, 800],
            "hang_timeout_s": 60,
            "settle_s": 2,
            "diff_threshold": 32,
        },
        "headline": {
            "sites": 1,
            "skipped": 1,
            "servo_crash_sites": 0,
            "servo_hang_sites": 0,
            "servo_crash_rate": 0.0,
            "servo_hang_rate": 0.0,
            "load_ratio_median": 1.5,
            "visual_diff_median": 12.25,
            "chrome_failure_sites": 0,
        },
        "sites": [
            {
                "id": "wikipedia-web-browser",
                "category": "wiki",
                "url": "https://en.wikipedia.org/wiki/Web_browser",
                "status": "measured",
                "servo": browser(),
                "chrome": browser(load=80.0),
                "load_ratio": 1.5,
                "visual_diff_pct": 12.25,
                "thumbs": None,
            },
            {
                "id": "legatus-pane-shell",
                "category": "app",
                "url": None,
                "status": "skipped",
                "skip_reason": "private source not available",
            },
        ],
    }


class SchemaTest(unittest.TestCase):
    def test_valid_document(self):
        self.assertEqual(schema.validate(valid_doc()), [])

    def test_document_round_trips_through_json(self):
        doc = json.loads(json.dumps(valid_doc()))
        self.assertEqual(schema.validate(doc), [])

    def test_missing_top_level_key(self):
        doc = valid_doc()
        del doc["headline"]
        self.assertIn("missing key: headline", schema.validate(doc))

    def test_wrong_schema_id(self):
        doc = valid_doc()
        doc["schema"] = "something/else"
        self.assertTrue(any("schema" in e for e in schema.validate(doc)))

    def test_bad_date(self):
        doc = valid_doc()
        doc["date"] = "27/09/2026"
        self.assertTrue(any("date" in e for e in schema.validate(doc)))

    def test_bad_run_status(self):
        doc = valid_doc()
        doc["sites"][0]["servo"]["runs"][0]["status"] = "exploded"
        self.assertTrue(any("status" in e for e in schema.validate(doc)))

    def test_negative_load(self):
        doc = valid_doc()
        doc["sites"][0]["chrome"]["load_ms"] = -1
        self.assertTrue(any("load_ms" in e for e in schema.validate(doc)))

    def test_diff_out_of_range(self):
        doc = valid_doc()
        doc["sites"][0]["visual_diff_pct"] = 100.5
        self.assertTrue(any("visual_diff_pct" in e for e in schema.validate(doc)))

    def test_rate_out_of_range(self):
        doc = valid_doc()
        doc["headline"]["servo_crash_rate"] = 1.5
        self.assertTrue(any("servo_crash_rate" in e for e in schema.validate(doc)))

    def test_skipped_site_needs_reason(self):
        doc = valid_doc()
        del doc["sites"][1]["skip_reason"]
        self.assertTrue(any("skip_reason" in e for e in schema.validate(doc)))

    def test_duplicate_site_ids(self):
        doc = valid_doc()
        doc["sites"].append(copy.deepcopy(doc["sites"][0]))
        self.assertTrue(any("duplicate" in e for e in schema.validate(doc)))

    def test_bool_is_not_a_number(self):
        doc = valid_doc()
        doc["sites"][0]["servo"]["load_ms"] = True
        self.assertTrue(any("load_ms" in e for e in schema.validate(doc)))


class SitesFileTest(unittest.TestCase):
    """The committed site list is well formed."""

    def test_sites_json(self):
        with open(os.path.join(HERE, "..", "sites.json"), encoding="utf-8") as f:
            sites = json.load(f)
        self.assertEqual(schema.validate_sites(sites), [])

    def test_sites_validator_rejects_bad_id(self):
        errors = schema.validate_sites(
            {"version": 1, "sites": [{"id": "Bad Id!", "category": "x", "url": "https://a", "license": "x"}]}
        )
        self.assertTrue(any("id" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
