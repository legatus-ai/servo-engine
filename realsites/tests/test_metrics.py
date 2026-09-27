"""Unit tests for rs.metrics: medians, per-site aggregation, headline numbers."""

import unittest

from rs import metrics


class MedianTest(unittest.TestCase):
    def test_odd_count(self):
        self.assertEqual(metrics.median([30.0, 10.0, 20.0]), 20.0)

    def test_even_count_averages_middle_pair(self):
        self.assertEqual(metrics.median([4.0, 1.0, 3.0, 2.0]), 2.5)

    def test_ignores_missing_values(self):
        self.assertEqual(metrics.median([None, 5.0, None, 7.0, 9.0]), 7.0)

    def test_empty_is_none(self):
        self.assertIsNone(metrics.median([]))
        self.assertIsNone(metrics.median([None, None]))

    def test_single_value(self):
        self.assertEqual(metrics.median([42.0]), 42.0)


class RatioTest(unittest.TestCase):
    def test_ratio(self):
        self.assertEqual(metrics.ratio(300.0, 100.0), 3.0)

    def test_ratio_missing_or_zero(self):
        self.assertIsNone(metrics.ratio(None, 100.0))
        self.assertIsNone(metrics.ratio(100.0, None))
        self.assertIsNone(metrics.ratio(100.0, 0.0))


def run(status, load=None, fp=None, detail=None):
    return {"status": status, "load_ms": load, "first_paint_ms": fp, "detail": detail}


class AggregateBrowserTest(unittest.TestCase):
    def test_all_ok_takes_medians(self):
        agg = metrics.aggregate_browser([run("ok", 300, 100), run("ok", 100, 50), run("ok", 200, 70)])
        self.assertEqual(agg["status"], "ok")
        self.assertEqual(agg["load_ms"], 200)
        self.assertEqual(agg["first_paint_ms"], 70)
        self.assertIsNone(agg["panic"])
        self.assertEqual(agg["crashes"], 0)
        self.assertEqual(agg["hangs"], 0)

    def test_crash_wins_over_hang_and_keeps_first_panic(self):
        agg = metrics.aggregate_browser(
            [
                run("hang", detail="no load within 60 s"),
                run("crash", detail="boom (thread Script, at a.rs:1)"),
                run("ok", 500, 90),
            ]
        )
        self.assertEqual(agg["status"], "crash")
        self.assertEqual(agg["panic"], "boom (thread Script, at a.rs:1)")
        self.assertEqual(agg["crashes"], 1)
        self.assertEqual(agg["hangs"], 1)
        # Medians only use the runs that loaded.
        self.assertEqual(agg["load_ms"], 500)

    def test_hang_only(self):
        agg = metrics.aggregate_browser([run("hang"), run("ok", 10), run("ok", 30)])
        self.assertEqual(agg["status"], "hang")
        self.assertEqual(agg["load_ms"], 20)

    def test_error_only_when_nothing_worse(self):
        agg = metrics.aggregate_browser([run("error", detail="session refused"), run("ok", 10)])
        self.assertEqual(agg["status"], "error")

    def test_no_runs_is_error(self):
        self.assertEqual(metrics.aggregate_browser([])["status"], "error")


def site(sid, servo_status, servo_load, chrome_status, chrome_load, diff):
    return {
        "id": sid,
        "status": "measured",
        "servo": {"status": servo_status, "load_ms": servo_load},
        "chrome": {"status": chrome_status, "load_ms": chrome_load},
        "visual_diff_pct": diff,
    }


class HeadlineTest(unittest.TestCase):
    def test_headline_numbers(self):
        sites = [
            site("a", "ok", 200.0, "ok", 100.0, 10.0),  # ratio 2
            site("b", "ok", 300.0, "ok", 100.0, 20.0),  # ratio 3
            site("c", "crash", None, "ok", 100.0, None),
            site("d", "hang", 900.0, "ok", 100.0, 40.0),  # ratio 9
            {"id": "e", "status": "skipped", "skip_reason": "no snapshot"},
        ]
        head = metrics.headline(sites)
        self.assertEqual(head["sites"], 4)
        self.assertEqual(head["skipped"], 1)
        self.assertEqual(head["servo_crash_sites"], 1)
        self.assertEqual(head["servo_hang_sites"], 1)
        self.assertAlmostEqual(head["servo_crash_rate"], 0.25)
        self.assertAlmostEqual(head["servo_hang_rate"], 0.25)
        self.assertEqual(head["load_ratio_median"], 3.0)
        self.assertEqual(head["visual_diff_median"], 20.0)
        self.assertEqual(head["chrome_failure_sites"], 0)

    def test_empty(self):
        head = metrics.headline([])
        self.assertEqual(head["sites"], 0)
        self.assertIsNone(head["servo_crash_rate"])
        self.assertIsNone(head["load_ratio_median"])


class WorstTest(unittest.TestCase):
    def test_worst_orders_by_diff_then_failures(self):
        sites = [
            site("a", "ok", 1, "ok", 1, 10.0),
            site("b", "ok", 1, "ok", 1, 55.5),
            site("c", "crash", None, "ok", 1, None),
            site("d", "ok", 1, "ok", 1, 30.0),
        ]
        self.assertEqual([s["id"] for s in metrics.worst(sites, 3)], ["c", "b", "d"])


if __name__ == "__main__":
    unittest.main()
