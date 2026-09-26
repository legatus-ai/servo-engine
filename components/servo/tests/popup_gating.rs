/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row 12: `window.open` / `target=_blank` popup gating on transient activation.
//!
//! RED-first: asserts the desired end state. Currently RED — Servo's
//! `choose_a_navigable` step 8 is an unimplemented TODO
//! (`components/script/dom/window/windowproxy.rs`), so popups open
//! regardless of activation and nothing is ever consumed.
//!
//! Desired end state (spec choosing-a-navigable step 8, first option):
//! - (a) script `window.open` with no gesture returns null and the embedder
//!   sees no `request_create_new` call;
//! - (b) a native click handler calling `window.open` twice: first allowed
//!   (non-null + one embedder request), second blocked (null, still one
//!   request) — the allowed popup consumes transient activation;
//! - (c) a native click on `<a target=_blank>` is allowed (second request);
//! - (d) a scripted `.click()` on the anchor with no ambient activation is
//!   blocked (still two requests); a scripted click WITH ambient transient
//!   activation (fresh native click elsewhere first) is allowed (control:
//!   proves (d) is about activation, not a broken link).

mod common;

use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::time::{Duration, Instant};

use common::{ServoTest, click_at_point, evaluate_javascript};
use http_body_util::combinators::BoxBody;
use hyper::body::{Bytes, Incoming};
use hyper::{Request as HyperRequest, Response as HyperResponse};
use net::test_util::{make_body, make_server};
use servo::{
    CreateNewWebViewRequest, DevicePoint, JSValue, LoadStatus, MouseButton, RenderingContext,
    WebView, WebViewBuilder, WebViewDelegate,
};

static PAGE_HTML: &str = r#"<!doctype html><html><body style="margin:0">
<button id="openBtn" style="position:absolute;left:10px;top:10px;width:120px;height:40px">open</button>
<a id="blankLink" href="about:blank#popup" target="_blank" style="position:absolute;left:10px;top:60px;width:120px;height:40px;display:block">popup</a>
<button id="noopBtn" style="position:absolute;left:10px;top:110px;width:120px;height:40px">noop</button>
<script>
window.__openDone = false;
window.__firstNull = 'unset';
window.__secondNull = 'unset';
document.getElementById('openBtn').addEventListener('click', () => {
  const first = window.open('about:blank');
  const second = window.open('about:blank');
  window.__firstNull = (first === null) ? 'null' : 'object';
  window.__secondNull = (second === null) ? 'null' : 'object';
  window.__openDone = true;
});
</script>
</body></html>"#;

struct PopupCountingDelegate {
    rendering_context: Rc<dyn RenderingContext>,
    new_frame_ready: Cell<bool>,
    popup_requests: Cell<usize>,
    popups: RefCell<Vec<WebView>>,
}

impl WebViewDelegate for PopupCountingDelegate {
    fn notify_new_frame_ready(&self, webview: WebView) {
        self.new_frame_ready.set(true);
        webview.paint();
    }

    fn request_create_new(&self, parent_webview: WebView, request: CreateNewWebViewRequest) {
        self.popup_requests.set(self.popup_requests.get() + 1);
        let popup = request
            .builder(self.rendering_context.clone())
            .delegate(parent_webview.delegate())
            .build();
        self.popups.borrow_mut().push(popup);
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

/// Spin the event loop for `duration` while asserting `condition` keeps
/// holding (absence proofs are only meaningful if the loop runs).
fn spin_while_holding(
    servo_test: &ServoTest,
    duration: Duration,
    description: &str,
    condition: impl Fn() -> bool,
) {
    let start = Instant::now();
    while start.elapsed() < duration {
        assert!(condition(), "{description}");
        servo_test.servo().spin_event_loop();
        std::thread::sleep(Duration::from_millis(1));
    }
}

fn eval_string(servo_test: &ServoTest, webview: &WebView, script: &str) -> String {
    match evaluate_javascript(servo_test, webview.clone(), script) {
        Ok(JSValue::String(value)) => value,
        Ok(JSValue::Boolean(value)) => value.to_string(),
        other => panic!("expected string-ish JS result for {script:?}, got {other:?}"),
    }
}

#[test]
fn popup_blocker_gates_new_traversables_on_transient_activation() {
    static MESSAGE: &[u8] = PAGE_HTML.as_bytes();
    let handler =
        move |_: HyperRequest<Incoming>, response: &mut HyperResponse<BoxBody<Bytes, hyper::Error>>| {
            *response.body_mut() = make_body(MESSAGE.to_vec());
        };
    // Note: the engine must be created BEFORE the test server (see pending_load.rs).
    let servo_test = ServoTest::new_with_builder(|builder| {
        let mut preferences = servo::Preferences::default();
        preferences.network_http_proxy_uri = String::new();
        preferences.network_https_proxy_uri = String::new();
        builder.preferences(preferences)
    });
    let (server, url) = make_server(handler);
    let page_url = url.as_url().clone();

    let delegate = Rc::new(PopupCountingDelegate {
        rendering_context: servo_test.rendering_context.clone(),
        new_frame_ready: Cell::new(false),
        popup_requests: Cell::new(0),
        popups: RefCell::new(Vec::new()),
    });
    let webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .url(page_url)
        .build();

    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "page to finish loading",
        || webview.load_status() == LoadStatus::Complete,
    );

    // Shown-webview + first-frame dance so the document is fully active and
    // click hit-testing has layout (mirrors activation.rs).
    delegate.new_frame_ready.set(false);
    let _ = evaluate_javascript(
        &servo_test,
        webview.clone(),
        "requestAnimationFrame(() => { \
           document.body.style.background = 'red'; \
           document.body.style.background = 'green'; \
         });",
    );
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "first frame after load",
        || delegate.new_frame_ready.get(),
    );

    // Sanity: controls must be where the clicks will land (CSS px).
    let rects = eval_string(
        &servo_test,
        &webview,
        "JSON.stringify([ \
           document.getElementById('openBtn').getBoundingClientRect(), \
           document.getElementById('blankLink').getBoundingClientRect() \
         ])",
    );
    assert!(
        rects.contains("\"x\":10") && rects.contains("\"y\":10"),
        "open button must sit at (10,10), got {rects}"
    );
    assert!(
        rects.contains("\"y\":60"),
        "anchor must sit at y=60, got {rects}"
    );

    // PHASE (a): script window.open with no gesture — null, no embedder request.
    // NOTE: spin the absence window BEFORE reading the return: with the
    // pre-fix code the popup opens asynchronously behind a non-null return,
    // so both halves must be asserted.
    let open_result = evaluate_javascript(&servo_test, webview.clone(), "window.open('about:blank')");
    spin_while_holding(
        &servo_test,
        Duration::from_secs(2),
        "script-driven window.open must not reach the embedder",
        || delegate.popup_requests.get() == 0,
    );
    assert!(
        matches!(open_result, Ok(JSValue::Null)),
        "script-driven window.open with no gesture must return null, got {open_result:?}"
    );

    // PHASE (b): native click handler opens twice — first allowed, second
    // consumed-blocked. Pump first: script blocks in the create round-trip
    // until the test thread's spin delivers the embedder response.
    click_at_point(
        &webview,
        DevicePoint::new(70.0, 30.0),
        MouseButton::Primary,
    );
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "open handler to run",
        || eval_string(&servo_test, &webview, "String(window.__openDone)") == "true",
    );
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "first popup request to reach the embedder",
        || delegate.popup_requests.get() == 1,
    );
    let first = eval_string(&servo_test, &webview, "window.__firstNull");
    let second = eval_string(&servo_test, &webview, "window.__secondNull");
    assert_eq!(first, "object", "first window.open under activation must succeed");
    assert_eq!(
        second, "null",
        "second window.open in the same handler must be consumed-blocked"
    );
    let is_active = eval_string(
        &servo_test,
        &webview,
        "String(navigator.userActivation.isActive)",
    );
    assert_eq!(
        is_active, "false",
        "the allowed popup must have consumed transient activation"
    );

    // PHASE (c): native click on <a target=_blank> — allowed (fresh gesture).
    click_at_point(
        &webview,
        DevicePoint::new(70.0, 80.0),
        MouseButton::Primary,
    );
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "anchor popup request to reach the embedder",
        || delegate.popup_requests.get() == 2,
    );

    // PHASE (d): scripted .click() with no ambient activation — blocked.
    // (c) consumed the click's activation, so none is left; assert that
    // first to prove the block is about activation, not a broken link.
    let is_active = eval_string(
        &servo_test,
        &webview,
        "String(navigator.userActivation.isActive)",
    );
    assert_eq!(
        is_active, "false",
        "no ambient activation may remain after (c) consumed it"
    );
    let _ = eval_string(
        &servo_test,
        &webview,
        "document.getElementById('blankLink').click(); 'clicked'",
    );
    spin_while_holding(
        &servo_test,
        Duration::from_secs(2),
        "scripted anchor click must not reach the embedder",
        || delegate.popup_requests.get() == 2,
    );

    // PHASE (d-control): scripted .click() WITH ambient transient activation
    // (fresh native click on a harmless button first) — allowed.
    click_at_point(
        &webview,
        DevicePoint::new(70.0, 130.0),
        MouseButton::Primary,
    );
    spin_until(
        &servo_test,
        Duration::from_secs(15),
        "noop click to stamp fresh activation",
        || {
            eval_string(&servo_test, &webview, "String(navigator.userActivation.isActive)")
                == "true"
        },
    );
    let _ = eval_string(
        &servo_test,
        &webview,
        "document.getElementById('blankLink').click(); 'clicked'",
    );
    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "scripted anchor click under activation to reach the embedder",
        || delegate.popup_requests.get() == 3,
    );

    delegate.popups.borrow_mut().clear();
    let _ = server.close();
}
