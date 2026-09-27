"""Unit tests for rs.classify: run outcome and panic extraction."""

import unittest

from rs import classify

SERVO_HOOK_STDERR = """\
[2026-09-26T10:00:00Z WARN servoshell::panic_hook] Panic hook called.
called `Option::unwrap()` on a `None` value (thread Script(1,1), at components/script/dom/node.rs:1234)
stack backtrace:
   0: servoshell::backtrace::print
"""

RUST_DEFAULT_STDERR = """\
some log line
thread 'LayoutThread' panicked at components/layout/flow.rs:77:9:
index out of bounds: the len is 3 but the index is 7
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
"""


class ExtractPanicTest(unittest.TestCase):
    def test_servo_panic_hook_format(self):
        self.assertEqual(
            classify.extract_panic(SERVO_HOOK_STDERR),
            "called `Option::unwrap()` on a `None` value (thread Script(1,1), at components/script/dom/node.rs:1234)",
        )

    def test_rust_default_format_is_normalized(self):
        self.assertEqual(
            classify.extract_panic(RUST_DEFAULT_STDERR),
            "index out of bounds: the len is 3 but the index is 7 (thread LayoutThread, at components/layout/flow.rs:77:9)",
        )

    def test_first_panic_wins(self):
        text = "a (thread A, at x.rs:1)\nb (thread B, at y.rs:2)\n"
        self.assertEqual(classify.extract_panic(text), "a (thread A, at x.rs:1)")

    def test_no_panic(self):
        self.assertIsNone(classify.extract_panic("all fine\nloaded\n"))
        self.assertIsNone(classify.extract_panic(""))

    def test_long_message_is_truncated(self):
        text = ("x" * 1000) + " (thread T, at a.rs:1)\n"
        self.assertLessEqual(len(classify.extract_panic(text)), classify.MAX_DETAIL)


class ClassifyRunTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(
            classify.classify_run(exit_code=None, timed_out=False, stderr="", webdriver_error=None),
            ("ok", None),
        )

    def test_panic_exit_is_crash_with_panic_line(self):
        status, detail = classify.classify_run(
            exit_code=-11, timed_out=False, stderr=SERVO_HOOK_STDERR, webdriver_error="connection refused"
        )
        self.assertEqual(status, "crash")
        self.assertTrue(detail.startswith("called `Option::unwrap()`"))

    def test_signal_without_panic(self):
        self.assertEqual(
            classify.classify_run(exit_code=-11, timed_out=False, stderr="", webdriver_error=None),
            ("crash", "killed by signal SIGSEGV"),
        )

    def test_nonzero_exit_without_panic(self):
        self.assertEqual(
            classify.classify_run(exit_code=101, timed_out=False, stderr="", webdriver_error=None),
            ("crash", "exited with code 101"),
        )

    def test_unexpected_clean_exit_is_crash(self):
        self.assertEqual(
            classify.classify_run(exit_code=0, timed_out=False, stderr="", webdriver_error=None),
            ("crash", "exited with code 0 before the run finished"),
        )

    def test_panic_while_alive_is_crash(self):
        status, _ = classify.classify_run(
            exit_code=None, timed_out=False, stderr=RUST_DEFAULT_STDERR, webdriver_error=None
        )
        self.assertEqual(status, "crash")

    def test_crash_beats_timeout(self):
        status, _ = classify.classify_run(
            exit_code=-6, timed_out=True, stderr="", webdriver_error="timeout"
        )
        self.assertEqual(status, "crash")

    def test_timeout_alive_is_hang(self):
        self.assertEqual(
            classify.classify_run(exit_code=None, timed_out=True, stderr="", webdriver_error="timeout"),
            ("hang", "no load within 60 s"),
        )

    def test_chrome_tab_crash_is_crash(self):
        status, detail = classify.classify_run(
            exit_code=None,
            timed_out=False,
            stderr="",
            webdriver_error="unknown error: session deleted because of page crash\nfrom tab crashed",
        )
        self.assertEqual(status, "crash")
        self.assertEqual(detail, "unknown error: session deleted because of page crash")

    def test_other_webdriver_error_is_error(self):
        self.assertEqual(
            classify.classify_run(
                exit_code=None, timed_out=False, stderr="", webdriver_error="unsupported operation: x"
            ),
            ("error", "unsupported operation: x"),
        )


if __name__ == "__main__":
    unittest.main()
