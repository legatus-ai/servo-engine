/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row 11 (a): embedder-driven trusted native input produces transient activation.
//!
//! RED-first: asserts the desired end state. Currently RED — Servo's embedder
//! native-input path does not stamp user activation, so the click/keydown
//! phases observe no clipboard write instead of the probe text.
//!
//! Design notes:
//! - The ONLY activation-notification path in script is `Event::dispatch_inner`
//!   for activation-triggering input events (trusted keydown-non-Esc /
//!   mousedown / pointerdown-mouse / pointerup-non-mouse / touchend) —
//!   `components/script/dom/event/event.rs`. Embedder `evaluate_javascript`
//!   does NOT signal activation, so the PHASE 0 getter control is valid.
//! - The shown-webview + first-frame dance (mirroring
//!   `common::show_webview_and_wait_for_rendering_to_be_ready`) is required:
//!   without it the document is not fully active and click hit-testing has
//!   no layout.
//! - (d) `window.open` popup gating is NOT asserted: `choose_browsing_context`
//!   step 8 is an unimplemented TODO
//!   (`components/script/dom/window/windowproxy.rs`), so Servo opens popups
//!   regardless of activation. Documented in the tracker, not implemented
//!   (out of scope).

mod common;

use std::cell::Cell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use common::{ServoTest, click_at_point, evaluate_javascript};
use http_body_util::combinators::BoxBody;
use hyper::body::{Bytes, Incoming};
use hyper::{Request as HyperRequest, Response as HyperResponse};
use net::test_util::{make_body, make_server};
use servo::{
    ClipboardDelegate, DevicePoint, InputEvent, JSValue, Key, KeyState, KeyboardEvent,
    LoadStatus, MouseButton, WebView, WebViewBuilder, WebViewDelegate,
};

const PAGE_TEXT: &str = "row11-activation-probe";

static PAGE_HTML: &str = r#"<!doctype html><html><body style="margin:0">
<button id="copyBtn" style="position:absolute;left:10px;top:10px;width:120px;height:40px">copy</button>
<script>
window.__clickCopy = null;
window.__keyCopy = null;
document.getElementById('copyBtn').addEventListener('click', () => {
  let outcome;
  try {
    outcome = document.execCommand('copy') ? 'true' : 'false';
  } catch (e) {
    outcome = 'threw:' + e;
  }
  window.__clickCopy = outcome;
});
window.addEventListener('keydown', () => {
  let outcome;
  try {
    outcome = document.execCommand('copy') ? 'true' : 'false';
  } catch (e) {
    outcome = 'threw:' + e;
  }
  window.__keyCopy = outcome;
});
</script>
</body></html>"#;

#[derive(Default)]
struct ActivationDelegate {
    new_frame_ready: Cell<bool>,
}

impl WebViewDelegate for ActivationDelegate {
    fn notify_new_frame_ready(&self, webview: WebView) {
        self.new_frame_ready.set(true);
        webview.paint();
    }
}

struct TestClipboard {
    sender: std::sync::mpsc::Sender<String>,
}

impl ClipboardDelegate for TestClipboard {
    fn set_text(&self, _webview: WebView, new_contents: String) {
        let _ = self.sender.send(new_contents);
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

fn eval_string(servo_test: &ServoTest, webview: &WebView, script: &str) -> String {
    match evaluate_javascript(servo_test, webview.clone(), script) {
        Ok(JSValue::String(value)) => value,
        Ok(JSValue::Boolean(value)) => value.to_string(),
        other => panic!("expected string-ish JS result for {script:?}, got {other:?}"),
    }
}

#[test]
fn embedder_input_produces_transient_activation() {
    static MESSAGE: &[u8] = PAGE_HTML.as_bytes();
    let handler =
        move |_: HyperRequest<Incoming>, response: &mut HyperResponse<BoxBody<Bytes, hyper::Error>>| {
            *response.body_mut() = make_body(MESSAGE.to_vec());
        };
    // Note: the engine must be created BEFORE the test server (see pending_load.rs).
    let servo_test = ServoTest::new();
    let (server, url) = make_server(handler);
    let page_url = url.as_url().clone();

    let (clip_tx, clip_rx) = std::sync::mpsc::channel();
    let delegate = Rc::new(ActivationDelegate::default());
    let clipboard = Rc::new(TestClipboard { sender: clip_tx });
    let webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .clipboard_delegate(clipboard)
        .url(page_url)
        .build();

    spin_until(
        &servo_test,
        Duration::from_secs(30),
        "page to finish loading",
        || webview.load_status() == LoadStatus::Complete,
    );

    // Shown-webview + first-frame dance so the document is fully active
    // (mirrors `common::show_webview_and_wait_for_rendering_to_be_ready`).
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

    // Select the probe text so execCommand('copy') has something to copy.
    let selected = eval_string(
        &servo_test,
        &webview,
        &format!(
            "document.body.innerHTML += '<p id=probe>{PAGE_TEXT}</p>'; \
             const r = document.createRange(); \
             r.selectNodeContents(document.getElementById('probe')); \
             getSelection().removeAllRanges(); getSelection().addRange(r); 'selected'"
        ),
    );
    assert_eq!(selected, "selected");

    // PHASE 0 (control): no gesture yet — transient activation must be absent.
    let is_active_before = eval_string(
        &servo_test,
        &webview,
        "String(navigator.userActivation.isActive)",
    );
    assert_eq!(
        is_active_before, "false",
        "control: isActive must be false before any gesture"
    );

    // PHASE 1: trusted native mouse click on the button.
    // Button spans x=10..130, y=10..50; click its center (70, 30).
    let _ = eval_string(&servo_test, &webview, "window.__clickCopy = null; 'reset'");
    click_at_point(&webview, DevicePoint::new(70.0, 30.0), MouseButton::Primary);
    spin_until(
        &servo_test,
        Duration::from_secs(15),
        "click handler to run",
        || eval_string(&servo_test, &webview, "String(window.__clickCopy)") != "null",
    );
    let click_outcome = eval_string(&servo_test, &webview, "String(window.__clickCopy)");
    let clipboard_text = clip_rx
        .recv_timeout(Duration::from_secs(10))
        .expect("click-phase copy to reach the embedder clipboard");
    assert_eq!(
        click_outcome, "true",
        "click handler copy must succeed under transient activation"
    );
    assert_eq!(
        clipboard_text, PAGE_TEXT,
        "click-phase copy must carry the probe text (transient activation)"
    );

    // PHASE 2: trusted native keydown (non-Escape) re-activates after the
    // click's transient activation was consumed by its copy.
    let _ = eval_string(&servo_test, &webview, "window.__keyCopy = null; 'reset'");
    webview.notify_input_event(InputEvent::Keyboard(KeyboardEvent::from_state_and_key(
        KeyState::Down,
        Key::Character("a".into()),
    )));
    spin_until(
        &servo_test,
        Duration::from_secs(15),
        "keydown handler to run",
        || eval_string(&servo_test, &webview, "String(window.__keyCopy)") != "null",
    );
    let key_outcome = eval_string(&servo_test, &webview, "String(window.__keyCopy)");
    let clipboard_text = clip_rx
        .recv_timeout(Duration::from_secs(10))
        .expect("keydown-phase copy to reach the embedder clipboard");
    assert_eq!(
        key_outcome, "true",
        "keydown handler copy must succeed under transient activation"
    );
    assert_eq!(
        clipboard_text, PAGE_TEXT,
        "keydown-phase copy must carry the probe text (transient activation)"
    );

    // PHASE 3 (consumption): the keydown copy consumed transient activation,
    // so a synchronous script-driven copy with no new gesture must fail.
    // <https://html.spec.whatwg.org/multipage/#consume-user-activation>
    let consume_state = eval_string(
        &servo_test,
        &webview,
        "document.execCommand('copy') + '/' + navigator.userActivation.isActive",
    );
    assert_eq!(
        consume_state, "false/false",
        "consumed transient activation: script-driven copy must fail and stay inactive"
    );
    assert!(
        clip_rx.recv_timeout(Duration::from_secs(2)).is_err(),
        "consumed copy must not write to the embedder clipboard"
    );

    let _ = server.close();
}
