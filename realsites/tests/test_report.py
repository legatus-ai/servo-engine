"""Unit tests for report.py: raw runs -> validated document -> HTML page."""

import unittest

import report
from rs import schema


def run(status, load=None, fp=None, detail=None):
    return {"status": status, "load_ms": load, "first_paint_ms": fp, "nav_ms": load, "detail": detail}


RAW = {
    "servo_version": "Servo 0.1.0-deadbeef",
    "chrome_version": "Google Chrome for Testing 154.0.8037.57",
    "config": {"runs": 3, "viewport": [1280, 800], "hang_timeout_s": 60, "settle_s": 2.0},
    "sites": [
        {
            "id": "fast-site",
            "category": "docs",
            "url": "https://example.org/fast",
            "status": "measured",
            "servo": {"runs": [run("ok", 200, 50), run("ok", 220, 55), run("ok", 180, 45)]},
            "chrome": {"runs": [run("ok", 100, 30), run("ok", 110, 31), run("ok", 90, 29)]},
            "shots": {"servo": "shots/fast-site.servo.png", "chrome": "shots/fast-site.chrome.png"},
        },
        {
            "id": "crashy-site",
            "category": "spa",
            "url": "https://example.org/<crash>",
            "status": "measured",
            "servo": {
                "runs": [
                    run("crash", detail="boom <script> (thread Script, at a.rs:1)"),
                    run("crash", detail="boom <script> (thread Script, at a.rs:1)"),
                    run("ok", 900, 300),
                ]
            },
            "chrome": {"runs": [run("ok", 300), run("ok", 300), run("ok", 300)]},
            "shots": {"chrome": "shots/crashy-site.chrome.png"},
        },
        {"id": "pane", "category": "app", "url": None, "status": "skipped", "skip_reason": "no bundle"},
    ],
}

META = {"build_run_id": 123, "artifact_created_at": "2026-09-27T00:00:00Z", "legatus_sha": "abc123"}


def fake_diff(servo_png, chrome_png):
    return 12.5 if servo_png and chrome_png else None


class BuildDocumentTest(unittest.TestCase):
    def setUp(self):
        self.doc = report.build_document(RAW, "2026-09-27", META, "chrome-version", fake_diff, threshold=32)

    def test_document_is_valid(self):
        self.assertEqual(schema.validate(self.doc), [])

    def test_site_numbers(self):
        fast = next(s for s in self.doc["sites"] if s["id"] == "fast-site")
        self.assertEqual(fast["servo"]["load_ms"], 200)
        self.assertEqual(fast["chrome"]["load_ms"], 100)
        self.assertEqual(fast["load_ratio"], 2.0)
        self.assertEqual(fast["visual_diff_pct"], 12.5)
        crashy = next(s for s in self.doc["sites"] if s["id"] == "crashy-site")
        self.assertEqual(crashy["servo"]["status"], "crash")
        self.assertEqual(crashy["servo"]["crashes"], 2)
        self.assertIsNone(crashy["visual_diff_pct"])

    def test_headline(self):
        head = self.doc["headline"]
        self.assertEqual(head["sites"], 2)
        self.assertEqual(head["skipped"], 1)
        self.assertEqual(head["servo_crash_rate"], 0.5)
        self.assertEqual(head["load_ratio_median"], 2.5)  # median of 2.0 and 3.0

    def test_chrome_version_prefers_raw(self):
        self.assertEqual(self.doc["chrome"]["version"], "Google Chrome for Testing 154.0.8037.57")


class HtmlTest(unittest.TestCase):
    def test_html_escapes_and_lists_sites(self):
        doc = report.build_document(RAW, "2026-09-27", META, "x", fake_diff, threshold=32)
        history = [{"date": "2026-09-26", "headline": dict(doc["headline"], load_ratio_median=3.0)}]
        page = report.render_html(doc, history, thumbs={})
        self.assertIn("fast-site", page)
        self.assertIn("crashy-site", page)
        self.assertIn("boom &lt;script&gt;", page)
        self.assertNotIn("boom <script>", page)
        self.assertIn('href="index.html"', page)
        self.assertIn("2026-09-26", page)
        self.assertIn("data/realsites-2026-09-27.json", page)

    def test_fmt(self):
        self.assertEqual(report.fmt_ms(None), "&ndash;")
        self.assertEqual(report.fmt_ms(1234.4), "1234")
        self.assertEqual(report.fmt_pct(None), "&ndash;")
        self.assertEqual(report.fmt_pct(3.14159), "3.1%")


if __name__ == "__main__":
    unittest.main()
