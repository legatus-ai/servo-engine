/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row #10 end-to-end acceptance (Ref BRO-53).
//!
//! Compiled only with the `test-registration-gate` cargo feature: the
//! tests hold a top-level registration open via
//! [`servo::registration_gate`], send a `LoadUrl` into the gap, and pin
//! both acceptance cases from the design note (§6):
//!
//! - (g) the parked load commits after registration (no blank window);
//! - (h) a context that never registers produces the embedder-visible
//!   `PendingLoadFailed(Expired)` within bound + ε on an otherwise idle
//!   engine.
//!
//! One `Servo` per binary: `Opts` is process-global (`OnceLock`), so a
//! second `ServoTest::new` in this binary would panic. Both phases share
//! a single `ServoTest`; the gate is re-armed between them (it is
//! reusable by design). The `GateGuard` releases the gate on drop so a
//! failure never leaves a pipeline blocked across shutdown.

#![cfg(feature = "test-registration-gate")]

mod common;

use std::cell::RefCell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use http_body_util::combinators::BoxBody;
use hyper::body::{Bytes, Incoming};
use hyper::{Request as HyperRequest, Response as HyperResponse};
use net::test_util::{make_body, make_server};
use servo::{PendingLoadFailure, WebView, WebViewBuilder, WebViewDelegate, registration_gate};
use url::Url;

use crate::common::ServoTest;

#[derive(Default)]
struct PendingLoadDelegate {
    title: RefCell<Option<String>>,
    url_changed: RefCell<Option<Url>>,
    failures: RefCell<Vec<(Url, PendingLoadFailure)>>,
}

impl WebViewDelegate for PendingLoadDelegate {
    fn notify_page_title_changed(&self, _webview: WebView, title: Option<String>) {
        *self.title.borrow_mut() = title;
    }

    fn notify_url_changed(&self, _webview: WebView, url: Url) {
        *self.url_changed.borrow_mut() = Some(url);
    }

    fn notify_pending_load_failed(
        &self,
        _webview: WebView,
        url: Url,
        reason: PendingLoadFailure,
    ) {
        self.failures.borrow_mut().push((url, reason));
    }
}

/// Release the registration gate when dropped. Every arm site holds one;
/// dropping it (even on panic) unblocks the waiting activation so the
/// engine can shut down.
struct GateGuard;

impl Drop for GateGuard {
    fn drop(&mut self) {
        registration_gate::release();
    }
}

/// Spin the event loop until `condition` holds, panicking after `timeout`
/// instead of hanging the harness forever.
fn spin_until(
    servo_test: &ServoTest,
    timeout: Duration,
    description: &str,
    condition: impl Fn() -> bool,
) {
    let start = Instant::now();
    while !condition() {
        servo_test.servo().spin_event_loop();
        std::thread::sleep(Duration::from_millis(1));
        assert!(
            start.elapsed() < timeout,
            "timed out waiting for {description}"
        );
    }
}

#[test]
fn registration_gap_parks_then_commits_and_expiry_fails_visibly() {
    static MESSAGE: &[u8] = b"<!DOCTYPE html>\n<title>Gap Page</title>Hello";
    let handler =
        move |_: HyperRequest<Incoming>, response: &mut HyperResponse<BoxBody<Bytes, hyper::Error>>| {
            *response.body_mut() = make_body(MESSAGE.to_vec());
        };
    let servo_test = ServoTest::new();

    // Note: the engine must be created BEFORE the test server. The net
    // resource thread initializes the process-global async runtime
    // unconditionally, while `make_server` only initializes it when not
    // already present — the reverse order panics in `init_async_runtime`.
    let (server, url) = make_server(handler);
    let page_url = url.as_url().clone();

    // Phase (g): a LoadUrl sent into the registration gap parks, then
    // commits once registration completes — no blank window. Note the
    // initial webview URL does NOT park: `handle_new_top_level_browsing_context`
    // builds the pipeline synchronously. Only a `LoadUrl` sent while the
    // context is still unregistered (script thread held at the gate)
    // enters the park table, so the test navigates after creation.
    registration_gate::arm();
    let guard = GateGuard;
    let delegate = Rc::new(PendingLoadDelegate::default());
    let webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .url(page_url.clone())
        .build();
    // The script thread blocks at the gate only after pipeline creation
    // is underway, which takes orders of magnitude longer than the
    // constellation takes to process messages sent at build: by the
    // time `entered` flips, a `load` sent now parks, not races.
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "activation to reach the gate",
        registration_gate::entered,
    );
    webview.load(page_url.clone());
    // While the gate is armed no commit is possible: the window is blank
    // (the bug's user-visible form) and stays blank.
    assert!(webview.page_title().is_none());
    servo_test.servo().spin_event_loop();
    std::thread::sleep(Duration::from_secs(1));
    servo_test.servo().spin_event_loop();
    assert!(
        webview.page_title().is_none(),
        "page committed while registration was still held open"
    );
    drop(guard);
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "parked load to commit after registration",
        || delegate.title.borrow().as_deref() == Some("Gap Page"),
    );
    assert_eq!(webview.url(), Some(page_url.clone()));

    // Phase (h): a context that never registers fails visibly within
    // bound + ε on an otherwise idle engine — no traffic but the test's
    // own event-loop spins. The failure notification can only come from
    // the park path (direct loads never emit it), so receiving it proves
    // the load parked.
    registration_gate::arm();
    let guard = GateGuard;
    let delegate = Rc::new(PendingLoadDelegate::default());
    let _webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .url(page_url.clone())
        .build();
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "activation to reach the gate",
        registration_gate::entered,
    );
    // The parkable event is the post-creation `LoadUrl`, not the initial
    // URL (see phase (g) note): without this nothing enters the park
    // table and there is nothing to expire.
    _webview.load(page_url.clone());
    let parked_at = Instant::now();
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "parked load to fail visibly",
        || !delegate.failures.borrow().is_empty(),
    );
    let failures = delegate.failures.borrow();
    assert_eq!(failures.len(), 1);
    assert_eq!(failures[0].0, page_url);
    assert_eq!(failures[0].1, PendingLoadFailure::Expired);
    // Gate builds shorten the bound to seconds (see
    // `pending_load_timeout`); the generous cap below proves the bound
    // fired on the idle engine rather than hanging or falling back to a
    // production-scale timeout.
    assert!(
        parked_at.elapsed() < Duration::from_secs(30),
        "expiry took {:?}, bound did not fire on the idle engine",
        parked_at.elapsed()
    );
    drop(guard);

    let _ = server.close();
}
