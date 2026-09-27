"""Unit tests for the scoreboard scorer: per-module aggregation, gap ranking,
missing-shard detection and the page. Standard library only:

    python3 -m unittest discover -s scoreboard -p 'test_*.py'

Fixtures live in scoreboard/testdata: wptreport-1/2 hold results, -3 is an
empty report and -4 is truncated (a shard killed mid-write). Both of those
count as missing shards.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import generate  # noqa: E402

REPORTS = [os.path.join(HERE, "testdata", f"wptreport-{i}.json") for i in (1, 2, 3, 4)]

# wpt.fyi summary_v2 shape: c = [passed subtests, total subtests], s = status
# letter. Tests without subtests have c = [0, 0].
CHROME = {
    "/css/css-grid/a.html": {"s": "O", "c": [3, 3]},
    "/css/css-grid/b.html": {"s": "P", "c": [0, 0]},
    "/css/css-flexbox/c.html": {"s": "O", "c": [2, 2]},
    "/css/css-flexbox/d.html": {"s": "P", "c": [0, 0]},
    "/selection/e.html": {"s": "O", "c": [2, 2]},
    "/css/css-text/f.html": {"s": "O", "c": [4, 4]},
    "/css/css-grid/g.html?variant=1": {"s": "O", "c": [2, 2]},
    "/css/css-flexbox/crashtests/h.html": {"s": "P", "c": [0, 0]},
    "/css/css-flexbox/skip.html": {"s": "P", "c": [0, 0]},
    "/css/css-ui/x.html": {"s": "O", "c": [5, 5]},
}
UPSTREAM = {
    "/css/css-grid/a.html": {"s": "O", "c": [2, 3]},
    "/css/css-grid/b.html": {"s": "F", "c": [0, 0]},
    "/css/css-flexbox/c.html": {"s": "O", "c": [2, 2]},
    "/css/css-flexbox/d.html": {"s": "P", "c": [0, 0]},
    "/selection/e.html": {"s": "O", "c": [1, 2]},
    "/css/css-text/f.html": {"s": "O", "c": [1, 4]},
    "/css/css-grid/g.html?variant=1": {"s": "O", "c": [0, 2]},
    "/css/css-ui/x.html": {"s": "O", "c": [0, 5]},
}


class ModuleOf(unittest.TestCase):
    def test_css_module_is_second_segment(self):
        self.assertEqual(generate.module_of("/css/css-grid/a.html"), "css-grid")
        self.assertEqual(generate.module_of("/css/CSS2/floats/f.xht"), "CSS2")
        self.assertEqual(generate.module_of("/css/css-grid/sub/x.html?a=1"), "css-grid")

    def test_non_css_has_no_module(self):
        self.assertIsNone(generate.module_of("/selection/e.html"))
        self.assertIsNone(generate.module_of("/cssom-view/x.html"))
        self.assertIsNone(generate.module_of("/css/top-level.html"))


class ForkReports(unittest.TestCase):
    def setUp(self):
        self.tests, self.present = generate.load_fork_reports(REPORTS)

    def test_empty_and_truncated_reports_are_not_present(self):
        self.assertEqual(self.present, [1, 2])
        self.assertEqual(generate.missing_shards(4, self.present), [3, 4])
        self.assertEqual(generate.missing_shards(None, self.present), [])

    def test_per_test_subtest_counts(self):
        self.assertEqual(self.tests["/css/css-grid/a.html"], {"p": 1, "n": 3, "s": "O"})
        self.assertEqual(self.tests["/css/css-grid/b.html"], {"p": 0, "n": 0, "s": "F"})
        self.assertEqual(self.tests["/css/css-text/f.html"], {"p": 0, "n": 4, "s": "O"})

    def test_areas_still_counted(self):
        areas = generate.aggregate_areas(self.tests)
        self.assertEqual(areas["selection"], [1, 2])


class ModuleAggregation(unittest.TestCase):
    def test_fork_modules(self):
        tests, _ = generate.load_fork_reports(REPORTS)
        mods = generate.aggregate_modules(tests)
        self.assertEqual(sorted(mods), ["css-flexbox", "css-grid", "css-text"])
        self.assertEqual(mods["css-grid"],
                         {"pass": 2, "total": 5, "tests": 3, "ref_pass": 0, "ref_total": 1})
        # SKIP is neither a pass nor a fail.
        self.assertEqual(mods["css-flexbox"],
                         {"pass": 2, "total": 2, "tests": 4, "ref_pass": 2, "ref_total": 2})
        self.assertEqual(mods["css-text"],
                         {"pass": 0, "total": 4, "tests": 1, "ref_pass": 0, "ref_total": 0})

    def test_fyi_modules(self):
        mods = generate.aggregate_modules(generate.fyi_tests(CHROME))
        self.assertEqual(mods["css-ui"],
                         {"pass": 5, "total": 5, "tests": 1, "ref_pass": 0, "ref_total": 0})
        self.assertEqual(mods["css-flexbox"]["ref_pass"], 3)
        self.assertEqual(mods["css-flexbox"]["ref_total"], 3)

    def test_rows_sorted_by_gap_to_chrome_not_run_last(self):
        fork, _ = generate.load_fork_reports(REPORTS)
        rows = generate.module_rows(
            generate.aggregate_modules(fork),
            generate.aggregate_modules(generate.fyi_tests(UPSTREAM)),
            generate.aggregate_modules(generate.fyi_tests(CHROME)),
        )
        self.assertEqual([r["module"] for r in rows],
                         ["css-text", "css-grid", "css-flexbox", "css-ui"])
        self.assertEqual([r["gap"] for r in rows], [4, 3, 0, None])
        self.assertIsNone(rows[-1]["fork"])  # fork never ran css-ui
        self.assertEqual(rows[0]["upstream"]["pass"], 1)
        self.assertEqual(rows[0]["chrome"]["pct"], 100.0)

    def test_totals(self):
        fork, _ = generate.load_fork_reports(REPORTS)
        self.assertEqual(generate.css_total(generate.aggregate_modules(fork)),
                         {"pass": 4, "total": 11, "pct": 36.36, "tests": 8,
                          "ref_pass": 2, "ref_total": 3})
        up = generate.css_total(generate.aggregate_modules(generate.fyi_tests(UPSTREAM)))
        self.assertEqual((up["pass"], up["total"]), (5, 16))


class GapRanking(unittest.TestCase):
    def setUp(self):
        self.fork, _ = generate.load_fork_reports(REPORTS)
        self.up = generate.fyi_tests(UPSTREAM)
        self.chrome = generate.fyi_tests(CHROME)

    def test_ranked_css_only_fork_ran_chrome_ahead(self):
        gaps = generate.gap_list(self.fork, self.up, self.chrome, limit=50)
        flat = [t["test"] for m in gaps["modules"] for t in m["tests"]]
        # Non-CSS (selection), zero-gap (c.html) and tests the fork never ran
        # (css-ui/x.html) are excluded.
        self.assertEqual(sorted(flat), ["/css/css-grid/a.html",
                                        "/css/css-grid/g.html?variant=1",
                                        "/css/css-text/f.html"])
        self.assertEqual(gaps["candidates"], 3)
        # Groups ordered by their summed gap, tests by gap inside a group.
        self.assertEqual([(m["module"], m["gap"]) for m in gaps["modules"]],
                         [("css-text", 4), ("css-grid", 3)])
        grid = gaps["modules"][1]["tests"]
        self.assertEqual([t["test"] for t in grid],
                         ["/css/css-grid/a.html", "/css/css-grid/g.html?variant=1"])
        self.assertEqual(grid[0], {
            "test": "/css/css-grid/a.html", "gap": 2,
            "fork": {"pass": 1, "total": 3},
            "upstream": {"pass": 2, "total": 3},
            "chrome": {"pass": 3, "total": 3},
        })

    def test_limit_keeps_largest_gaps(self):
        gaps = generate.gap_list(self.fork, self.up, self.chrome, limit=2)
        flat = [t["test"] for m in gaps["modules"] for t in m["tests"]]
        self.assertEqual(flat, ["/css/css-text/f.html", "/css/css-grid/a.html"])
        self.assertEqual(gaps["limit"], 2)
        self.assertEqual(gaps["candidates"], 3)

    def test_reftest_failures_chrome_passes(self):
        gaps = generate.gap_list(self.fork, self.up, self.chrome, limit=50)
        self.assertEqual(gaps["no_subtest_failures"], {"css-grid": 1})


class Page(unittest.TestCase):
    def test_render_has_module_table_totals_and_missing_shards(self):
        fork, present = generate.load_fork_reports(REPORTS)
        data = generate.build_data(
            date="2026-09-27", fork_sha="abc123",
            fork=fork, upstream=generate.fyi_tests(UPSTREAM),
            chrome=generate.fyi_tests(CHROME),
            upstream_run={"id": 1, "browser_version": "0.6.0"},
            chrome_run={"id": 2, "browser_version": "156"},
            expected_shards=4, present_shards=present,
        )
        self.assertEqual(data["shards"], {"expected": 4, "present": [1, 2], "missing": [3, 4]})
        self.assertEqual([r["module"] for r in data["css_modules"]],
                         ["css-text", "css-grid", "css-flexbox", "css-ui"])
        self.assertEqual(data["runs"]["fork"]["css_total"]["pass"], 4)
        # Existing extra areas are kept.
        self.assertIn("selection", data["runs"]["fork"]["areas"])
        page = generate.render_html(data, [])
        self.assertIn("css-grid", page)
        self.assertIn("all CSS", page)
        self.assertIn("Missing shards: 3, 4", page)
        self.assertIn("data/2026-09-27-gaps.json", page)
        self.assertLess(page.index("css-text"), page.index("css-grid"))


if __name__ == "__main__":
    unittest.main()
