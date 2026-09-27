"""A minimal W3C WebDriver client (stdlib only), enough for load + screenshot.

Both servoshell (--webdriver=PORT) and chromedriver speak this protocol, so
the two browsers are driven through exactly the same calls.
"""

import base64
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Optional


class WebDriverError(Exception):
    """A WebDriver error response, or a transport failure talking to the driver."""

    def __init__(self, error: str, message: str = "", timed_out: bool = False):
        super().__init__(f"{error}: {message}" if message else error)
        self.error = error
        self.message = message
        # True when the page load timeout fired, or the driver stopped answering.
        self.timed_out = timed_out


class Session:
    def __init__(self, base_url: str, http_timeout: float):
        self.base = base_url.rstrip("/")
        self.http_timeout = http_timeout
        self.id: Optional[str] = None

    def _call(self, method: str, path: str, body: Any = None, timeout: Optional[float] = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.http_timeout) as resp:
                payload = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                value = json.loads(e.read() or b"{}").get("value", {})
            except ValueError:
                value = {}
            err = value.get("error", f"http {e.code}") if isinstance(value, dict) else f"http {e.code}"
            msg = value.get("message", "") if isinstance(value, dict) else ""
            raise WebDriverError(err, msg, timed_out=(err == "timeout")) from None
        except (socket.timeout, TimeoutError):
            raise WebDriverError("driver timeout", f"no answer to {method} {path}", timed_out=True) from None
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise WebDriverError("connection refused", str(reason)) from None
        return payload.get("value")

    def wait_ready(self, deadline_s: float) -> None:
        end = time.monotonic() + deadline_s
        last: Optional[Exception] = None
        while time.monotonic() < end:
            try:
                self._call("GET", "/status", timeout=2)
                return
            except WebDriverError as e:
                last = e
                time.sleep(0.1)
        raise WebDriverError("driver not ready", str(last))

    def start(self, capabilities: dict) -> None:
        value = self._call("POST", "/session", {"capabilities": {"alwaysMatch": capabilities}})
        self.id = value["sessionId"]

    def set_timeouts(self, page_load_ms: int, script_ms: int) -> None:
        self._call("POST", f"/session/{self.id}/timeouts", {"pageLoad": page_load_ms, "script": script_ms})

    def navigate(self, url: str, timeout: float) -> None:
        self._call("POST", f"/session/{self.id}/url", {"url": url}, timeout=timeout)

    def execute(self, script: str, args: Optional[list] = None) -> Any:
        return self._call("POST", f"/session/{self.id}/execute/sync", {"script": script, "args": args or []})

    def screenshot(self) -> bytes:
        return base64.b64decode(self._call("GET", f"/session/{self.id}/screenshot"))

    def quit(self) -> None:
        if self.id:
            try:
                self._call("DELETE", f"/session/{self.id}", timeout=10)
            except WebDriverError:
                pass
            self.id = None
