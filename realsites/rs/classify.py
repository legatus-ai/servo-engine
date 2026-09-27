"""Pure run classification: ok / crash / hang / error, plus the panic's first line."""

import re
import signal
from typing import Optional, Tuple

MAX_DETAIL = 300

# servoshell's panic hook: "<message> (thread <name>, at <file>:<line>)".
_SERVO_HOOK = re.compile(r"^(?P<msg>.+?) \(thread (?P<thread>.+?), at (?P<loc>[^()]+:\d+)\)\s*$")
# Rust's default hook: "thread '<name>' panicked at <file>:<line>:<col>:" then the message.
_RUST_DEFAULT = re.compile(r"^thread '(?P<thread>[^']*)' panicked at (?P<loc>\S+?):?\s*$")
# WebDriver errors that mean the browser or its page process died.
_WEBDRIVER_CRASH = re.compile(
    r"page crash|tab crashed|chrome not reachable|browser has closed|disconnected|"
    r"connection (refused|reset|aborted)|remote end closed",
    re.IGNORECASE,
)


def _truncate(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 3] + "..."


def extract_panic(stderr: str) -> Optional[str]:
    """The first panic in a browser's stderr, normalized to Servo's hook format."""
    lines = stderr.splitlines()
    for i, line in enumerate(lines):
        line = line.rstrip()
        m = _RUST_DEFAULT.match(line)
        if m:
            msg = lines[i + 1].strip() if i + 1 < len(lines) else "<no message>"
            return _truncate(f"{msg} (thread {m.group('thread')}, at {m.group('loc')})")
        m = _SERVO_HOOK.match(line)
        if m:
            return _truncate(line)
    return None


def _signal_name(code: int) -> str:
    try:
        return signal.Signals(-code).name
    except ValueError:
        return f"signal {-code}"


def classify_run(
    *,
    exit_code: Optional[int],
    timed_out: bool,
    stderr: str,
    webdriver_error: Optional[str],
    hang_timeout_s: int = 60,
) -> Tuple[str, Optional[str]]:
    """Classify one browser run.

    exit_code is the browser's exit status if it exited on its own before the
    harness shut it down, else None (still alive). A negative code is a
    signal, as reported by subprocess.
    """
    panic = extract_panic(stderr or "")
    if exit_code is not None:
        if panic:
            return "crash", panic
        if exit_code < 0:
            return "crash", f"killed by signal {_signal_name(exit_code)}"
        if exit_code == 0:
            return "crash", "exited with code 0 before the run finished"
        return "crash", f"exited with code {exit_code}"
    if panic:
        return "crash", panic
    if timed_out:
        return "hang", f"no load within {hang_timeout_s} s"
    if webdriver_error:
        first = webdriver_error.strip().splitlines()[0] if webdriver_error.strip() else "webdriver error"
        if _WEBDRIVER_CRASH.search(webdriver_error):
            return "crash", _truncate(first)
        return "error", _truncate(first)
    return "ok", None
