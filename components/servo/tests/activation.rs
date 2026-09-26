/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row #11 end-to-end acceptance: embedder-driven trusted native input
//! produces transient activation, unlocking the gated consumers.
//!
//! The pane drives Servo with the embedder's own mouse and key events. This
//! test proves, through the same path, that:
//!
//! - (a) a native left-click on a button whose handler calls
//!   `document.execCommand('copy')` returns true AND the clipboard request
//!   reaches the embedder (`ClipboardDelegate::set_text`);
//! - control: the same call from a timer, with no input, returns false and
//!   touches no clipboard;
//! - (b) a native non-Esc keydown does the same as the click;
//! - (c) the successful copy consumes the activation, so an immediate
//!   second copy is refused. Per <https://html.spec.whatwg.org/multipage/#consume-user-activation>
//!   as invoked by `handle_script_triggered_editing_action`
//!   (`components/script/dom/document/editing.rs`): after the copy changed
//!   (or was allowed to change) the clipboard, the window's activation is
//!   consumed, and the next script-triggered copy sees no transient
//!   activation.
//! - (d) window.open popup gating: NOT covered here. Servo does not gate
//!   popups on transient activation at all — the step-8 popup-blocker arm in
//!   `choose_browsing_context` is `TODO: Implement this`
//!   (`components/script/dom/window/windowproxy.rs`). Documented in the
//!   tracker; no implementation in this row.
//!
//! One `Servo` per binary (`Opts` is process-global), so all phases share a
//! single `ServoTest` in one `#[test]`.

mod common;

use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::time::{Duration, Instant};

use servo::{
    ClipboardDelegate, InputEvent, JSValue, Key, KeyState, KeyboardEvent, MouseButton,
    StringRequest, WebView, WebViewBuilder,
};
use url::Url;
use webrender_api::units::DevicePoint;

use crate::common::{
    ServoTest, WebViewDelegateImpl, click_at_point, evaluate_javascript,
    show_webview_and_wait_for_rendering_to_be_ready,
};

#[derive(Default)]
struct ActivationClipboardDelegate {
    data: RefCell<String>,
    sets: Cell<usize>,
}

impl ClipboardDelegate for ActivationClipboardDelegate {
    fn clear(&self, _webview: WebView) {
        *self.data.borrow_mut() = String::new();
    }

    fn get_text(&self, _webview: WebView, request: StringRequest) {
        request.success(self.data.borrow().clone());
    }

    fn set_text(&self, _webview: WebView, new_contents: String) {
        *self.data.borrow_mut() = new_contents;
        self.sets.set(self.sets.get() + 1);
    }
}

/// Evaluate `script`, expecting a boolean JS value.
fn read_bool(servo_test: &ServoTest, webview: &WebView, script: &str) -> JSValue {
    evaluate_javascript(servo_test, webview.clone(), script)
        .expect("javascript evaluation should succeed")
}

/// Spin the event loop until `script` evaluates to a boolean JS value
/// (used to wait for an in-page handler or timer to record its result —
/// until then it evaluates to `undefined` or another non-boolean),
/// panicking after `timeout` instead of hanging the harness forever.
/// Returns the recorded boolean.
fn spin_until_bool_recorded(
    servo_test: &ServoTest,
    webview: &WebView,
    timeout: Duration,
    description: &str,
    script: &str,
) -> bool {
    let start = Instant::now();
    loop {
        match read_bool(servo_test, webview, script) {
            JSValue::Boolean(value) => return value,
            _ => {
                servo_test.servo().spin_event_loop();
                std::thread::sleep(Duration::from_millis(1));
            },
        }
        assert!(
            start.elapsed() < timeout,
            "timed out waiting for {description}"
        );
    }
}

const PAGE: &str = "<!DOCTYPE html><html><head><style>body{margin:0}\
    button{position:absolute;left:0;top:0;width:200px;height:100px}</style></head>\
    <body><button id=\"copy\">Copy</button><p id=\"text\">abcdef</p><script>\
    function reselect(){document.getSelection().selectAllChildren(document.getElementById('text'));}\
    document.getElementById('copy').addEventListener('click',()=>{\
    reselect();window.__clickCopyResult=document.execCommand('copy');});\
    document.addEventListener('keydown',(e)=>{\
    if(e.key==='a'){reselect();window.__keyCopyResult=document.execCommand('copy');}});\
    </script></body></html>";

#[test]
fn embedder_input_produces_transient_activation() {
    let servo_test = ServoTest::new();
    let delegate = Rc::new(WebViewDelegateImpl::default());
    let clipboard_delegate = Rc::new(ActivationClipboardDelegate::default());
    let webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .url(Url::parse(format!("data:text/html,{PAGE}").as_str()).unwrap())
        .clipboard_delegate(clipboard_delegate.clone())
        .build();
    show_webview_and_wait_for_rendering_to_be_ready(&servo_test, &webview, &delegate);

    // Control: the same copy call from a timer, with no input anywhere in
    // the window's history, is refused and touches no clipboard.
    let _ = read_bool(
        &servo_test,
        &webview,
        "window.__timerCopyResult='pending';\
         setTimeout(()=>{window.__timerCopyResult=document.execCommand('copy');},10);\
         true",
    );
    assert_eq!(
        spin_until_bool_recorded(
            &servo_test,
            &webview,
            Duration::from_secs(30),
            "timer copy result",
            "window.__timerCopyResult",
        ),
        false,
        "timer-driven execCommand('copy') must be refused without activation",
    );
    assert_eq!(clipboard_delegate.sets.get(), 0);

    // Phase (a): a native left-click on the button. The mousedown is a
    // trusted activation-triggering input event, so the click handler runs
    // with transient activation: copy returns true and the text reaches
    // the embedder.
    click_at_point(&webview, DevicePoint::new(100.0, 50.0), MouseButton::Primary);
    assert_eq!(
        spin_until_bool_recorded(
            &servo_test,
            &webview,
            Duration::from_secs(30),
            "click copy result",
            "window.__clickCopyResult",
        ),
        true,
        "click-handler execCommand('copy') must succeed with activation",
    );
    let sets_after_click = clipboard_delegate.sets.get();
    assert!(sets_after_click > 0, "copy must reach the embedder");
    assert_eq!(*clipboard_delegate.data.borrow(), "abcdef");

    // Phase (b): a native non-Esc keydown does the same as the click.
    webview.notify_input_event(InputEvent::Keyboard(KeyboardEvent::from_state_and_key(
        KeyState::Down,
        Key::Character("a".to_string()),
    )));
    assert_eq!(
        spin_until_bool_recorded(
            &servo_test,
            &webview,
            Duration::from_secs(30),
            "keydown copy result",
            "window.__keyCopyResult",
        ),
        true,
        "keydown-handler execCommand('copy') must succeed with activation",
    );
    assert!(
        clipboard_delegate.sets.get() > sets_after_click,
        "keydown copy must reach the embedder"
    );
    assert_eq!(*clipboard_delegate.data.borrow(), "abcdef");

    // Phase (c): the successful copy consumed the activation, so an
    // immediate second copy — same window, well within the 5 s duration —
    // is refused and sends nothing to the embedder.
    let sets_before = clipboard_delegate.sets.get();
    assert_eq!(
        read_bool(&servo_test, &webview, "document.execCommand('copy')"),
        JSValue::Boolean(false),
        "second copy must be refused: the first copy consumed the activation",
    );
    assert_eq!(
        clipboard_delegate.sets.get(),
        sets_before,
        "refused copy must not reach the embedder"
    );
}
