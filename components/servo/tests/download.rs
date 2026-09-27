/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row #9b integration tests (Ref BRO-53): hyperlink navigations that
//! resolve to downloads must keep the page and report a
//! [`DownloadRequest`] instead of navigating.
//!
//! The r27 failure: clicking `<a id="dl" href="/file" download>` served
//! with `200` + `Content-Type: application/octet-stream` +
//! `Content-Disposition: attachment; filename="report.bin"` navigated to
//! Servo's "Unknown content type" page. `recognise_download` returns
//! `Download` for exactly these inputs, so the decision never ran for
//! the hyperlink path: `park_download_if_needed` looks the pipeline up
//! in the live documents, but a hyperlink navigation fetches into a NEW
//! pipeline that has no window yet, so the lookup misses and the load
//! sails through to document creation.

mod common;

use std::cell::RefCell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use http::{HeaderValue, header::CONTENT_DISPOSITION};
use http_body_util::combinators::BoxBody;
use hyper::body::{Bytes, Incoming};
use hyper::{Request as HyperRequest, Response as HyperResponse};
use net::test_util::{make_body, make_server};
use servo::{DownloadRequest, WebView, WebViewBuilder, WebViewDelegate};
use url::Url;

use crate::common::{ServoTest, evaluate_javascript};

/// How the delegate answers a download request.
#[derive(Clone, Copy, Default, PartialEq)]
enum Answer {
    /// Drop it unanswered: the default, which denies at once.
    #[default]
    Drop,
    /// Keep it and never answer: denied when the 10 s deadline expires.
    Hold,
    /// Allow it (still treated as deny until file writing lands).
    Allow,
}

/// Records history commits and download requests.
#[derive(Default)]
struct RecordingDelegate {
    history: RefCell<Vec<Url>>,
    downloads: RefCell<Vec<(Url, Option<String>)>>,
    answer: Answer,
    held: RefCell<Vec<DownloadRequest>>,
}

impl RecordingDelegate {
    fn answering(answer: Answer) -> Self {
        Self {
            answer,
            ..Self::default()
        }
    }
}

impl WebViewDelegate for RecordingDelegate {
    fn notify_history_changed(&self, _webview: WebView, entries: Vec<Url>, current: usize) {
        if let Some(url) = entries.get(current).cloned() {
            self.history.borrow_mut().push(url);
        }
    }

    fn notify_url_changed(&self, _webview: WebView, _url: Url) {}

    // Paint each frame, as an embedder does: a screenshot waits for one.
    fn notify_new_frame_ready(&self, webview: WebView) {
        webview.paint();
    }

    fn request_download(&self, _webview: WebView, request: DownloadRequest) {
        self.downloads
            .borrow_mut()
            .push((request.url.clone(), request.suggested_filename.clone()));
        match self.answer {
            // Drop without answering: the default, which denies and keeps
            // the current page.
            Answer::Drop => {},
            Answer::Hold => self.held.borrow_mut().push(request),
            Answer::Allow => request.allow(std::env::temp_dir().join("servo-download-test.bin")),
        }
    }
}

fn spin_until(servo_test: &ServoTest, what: &str, timeout: Duration, cond: impl Fn() -> bool) {
    let start = Instant::now();
    while !cond() {
        if start.elapsed() > timeout {
            panic!("timed out waiting for {what}");
        }
        servo_test.servo.spin_event_loop();
        std::thread::sleep(Duration::from_millis(1));
    }
}

/// A screenshot of the webview completes within a bound well past the
/// download decision's own 10 s deadline, and succeeds.
fn assert_screenshot_completes(servo_test: &ServoTest, webview: &WebView) {
    let result = Rc::new(RefCell::new(None));
    let slot = result.clone();
    webview.take_screenshot(None, move |shot| {
        *slot.borrow_mut() = Some(shot.is_ok());
    });
    spin_until(servo_test, "a screenshot", Duration::from_secs(20), || {
        result.borrow().is_some()
    });
    assert_eq!(*result.borrow(), Some(true), "the screenshot failed");
}

fn history_len(delegate: &RecordingDelegate) -> usize {
    delegate.history.borrow().len()
}

fn download_count(delegate: &RecordingDelegate) -> usize {
    delegate.downloads.borrow().len()
}

const PAGE: &str = r#"<!DOCTYPE html>
<html><body>
<a id="dl" href="/file" download>download</a>
<a id="plain" href="/file">plain link</a>
<a id="dl-text" href="/notes" download>notes</a>
<a id="article" href="/article">article</a>
<a id="empty" href="/nocontent">no content</a>
</body></html>"#;

/// Serve the page, an attachment octet-stream at /file, a plain
/// text (non-attachment) response at /notes, and a plain text/html
/// (non-attachment) page at /article.
fn serve_test_site() -> (net::test_util::Server, url::Url) {
    let handler =
        move |request: HyperRequest<Incoming>,
              response: &mut HyperResponse<BoxBody<Bytes, hyper::Error>>| {
            match request.uri().path() {
                "/file" => {
                    response.headers_mut().insert(
                        "content-type",
                        HeaderValue::from_static("application/octet-stream"),
                    );
                    response.headers_mut().insert(
                        CONTENT_DISPOSITION,
                        HeaderValue::from_static("attachment; filename=\"report.bin\""),
                    );
                    *response.body_mut() = make_body(b"binary-bytes".to_vec());
                },
                "/notes" => {
                    response
                        .headers_mut()
                        .insert("content-type", HeaderValue::from_static("text/plain"));
                    *response.body_mut() = make_body(b"just notes".to_vec());
                },
                "/nocontent" => {
                    *response.status_mut() = hyper::StatusCode::NO_CONTENT;
                },
                "/article" => {
                    response
                        .headers_mut()
                        .insert("content-type", HeaderValue::from_static("text/html"));
                    *response.body_mut() = make_body(b"<title>article</title>plain page".to_vec());
                },
                _ => {
                    *response.body_mut() = make_body(PAGE.as_bytes().to_vec());
                },
            }
        };
    let (server, url) = make_server(handler);
    (server, url.as_url().clone())
}

fn build_page(servo_test: &ServoTest, delegate: Rc<RecordingDelegate>, page: &Url) -> WebView {
    let webview = WebViewBuilder::new(servo_test.servo(), servo_test.rendering_context.clone())
        .delegate(delegate.clone())
        .url(page.clone())
        .build();
    spin_until(
        servo_test,
        "initial page commit",
        Duration::from_secs(30),
        || history_len(&delegate) > 0,
    );
    webview
}

fn click(servo_test: &ServoTest, webview: &WebView, id: &str) {
    evaluate_javascript(
        servo_test,
        webview.clone(),
        format!("document.getElementById('{id}').click()"),
    )
    .expect("click script runs");
}

/// All three download scenarios plus a normal-navigation guard in ONE
/// test: `Servo::new` initializes the process-global `Opts` exactly once,
/// so a second `ServoTest::new` in the same binary panics with "Already
/// initialized". One `Servo` instance serves all scenarios; each gets a
/// fresh delegate, server-side paths are shared, and each scenario builds
/// its own `WebView`.
///
/// The r27 case: `<a download>` to an attachment octet-stream.
/// The page must be kept and `request_download` must fire with the
/// attachment's filename.
#[test]
fn hyperlink_downloads_park_and_report() {
    let servo_test = ServoTest::new();
    let (server, page) = serve_test_site();

    // Scenario 0: the control. A screenshot completes with no download at
    // all, so a timeout below is the download's and not the harness's.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        assert_screenshot_completes(&servo_test, &webview);
    }

    // Scenario 1: attribute alone triggers — `<a download>` to a
    // same-origin non-attachment response is a download, not a navigation.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "dl-text");
        spin_until(
            &servo_test,
            "download request",
            Duration::from_secs(30),
            || download_count(&delegate) > 0,
        );
        let downloads = delegate.downloads.borrow();
        assert_eq!(downloads.len(), 1);
        assert!(downloads[0].0.as_str().ends_with("/notes"));
        assert_eq!(downloads[0].1, None);
        assert_eq!(history_len(&delegate), 1);
        assert_eq!(webview.url().as_ref(), Some(&page));
    }

    // Scenario 2: the r27 case — `<a download>` to an attachment
    // octet-stream keeps the page and reports the attachment filename.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "dl");
        spin_until(
            &servo_test,
            "download request",
            Duration::from_secs(30),
            || download_count(&delegate) > 0,
        );
        let downloads = delegate.downloads.borrow();
        assert_eq!(downloads.len(), 1);
        assert!(downloads[0].0.as_str().ends_with("/file"));
        assert_eq!(downloads[0].1.as_deref(), Some("report.bin"));
        // The page is kept: exactly the initial commit, still on the page.
        assert_eq!(history_len(&delegate), 1);
        assert_eq!(webview.url().as_ref(), Some(&page));
        // And it still paints. The denied download's new pipeline must
        // not stay a pending change: screenshot readiness waits on every
        // pending change, so a leftover one wedged every later screenshot
        // (the pane's r34 conformance run).
        assert_screenshot_completes(&servo_test, &webview);
    }

    // Scenario 3: header alone triggers — a plain link (no `download`
    // attribute) to an attachment response is still a download.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "plain");
        spin_until(
            &servo_test,
            "download request",
            Duration::from_secs(30),
            || download_count(&delegate) > 0,
        );
        let downloads = delegate.downloads.borrow();
        assert_eq!(downloads.len(), 1);
        assert!(downloads[0].0.as_str().ends_with("/file"));
        assert_eq!(downloads[0].1.as_deref(), Some("report.bin"));
        assert_eq!(history_len(&delegate), 1);
        assert_eq!(webview.url().as_ref(), Some(&page));
    }

    // Scenario 4: normal navigation guard — a plain link (no `download`
    // attribute) to a text/html page with no Content-Disposition must NOT
    // be parked. It navigates normally: no download fires and history
    // grows to the initial commit plus the new one.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "article");
        let article = page.join("article").expect("article url joins");
        spin_until(
            &servo_test,
            "article navigation commit",
            Duration::from_secs(30),
            || history_len(&delegate) == 2,
        );
        assert_eq!(download_count(&delegate), 0);
        assert_eq!(history_len(&delegate), 2);
        assert_eq!(webview.url().as_ref(), Some(&article));
        // A navigation that commits is not aborted: it still paints.
        assert_screenshot_completes(&servo_test, &webview);
    }

    // Scenario 5: the other deny path. The embedder holds the request and
    // never answers, so the download is denied when its 10 s deadline
    // expires. That path must drop the new pipeline's pending change too:
    // the screenshot can only complete once it has.
    {
        let delegate = Rc::new(RecordingDelegate::answering(Answer::Hold));
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "dl");
        spin_until(
            &servo_test,
            "download request",
            Duration::from_secs(30),
            || download_count(&delegate) > 0,
        );
        assert_eq!(
            delegate.held.borrow().len(),
            1,
            "the request is held, unanswered"
        );
        assert_screenshot_completes(&servo_test, &webview);
        assert_eq!(history_len(&delegate), 1);
        assert_eq!(webview.url().as_ref(), Some(&page));
    }

    // Scenario 6: the rule for allow as well as deny.
    allowed_download_keeps_page_painting(&servo_test, &page);

    // Scenario 7: the existing 204 abort, untouched by the download fix. A
    // link to a 204 response keeps the page, asks no download, and paints.
    {
        let delegate = Rc::new(RecordingDelegate::default());
        let webview = build_page(&servo_test, delegate.clone(), &page);
        click(&servo_test, &webview, "empty");
        // Let the navigation fetch and abort before the screenshot is asked.
        let clicked = Instant::now();
        spin_until(
            &servo_test,
            "the 204 navigation",
            Duration::from_secs(5),
            || clicked.elapsed() > Duration::from_secs(2),
        );
        assert_screenshot_completes(&servo_test, &webview);
        assert_eq!(download_count(&delegate), 0);
        assert_eq!(history_len(&delegate), 1);
        assert_eq!(webview.url().as_ref(), Some(&page));
    }

    let _ = server.close();
}

/// A download never commits a document, so its navigation pipeline is
/// abandoned whatever the embedder decides: an allowed download keeps the
/// page, and the page still paints. (Allow is treated as deny until file
/// writing lands; the rule holds after it does.) Run inside
/// `hyperlink_downloads_park_and_report`, whose `Servo` it shares.
fn allowed_download_keeps_page_painting(servo_test: &ServoTest, page: &Url) {
    let delegate = Rc::new(RecordingDelegate::answering(Answer::Allow));
    let webview = build_page(servo_test, delegate.clone(), page);
    click(servo_test, &webview, "dl");
    spin_until(
        servo_test,
        "download request",
        Duration::from_secs(30),
        || download_count(&delegate) > 0,
    );
    assert_screenshot_completes(servo_test, &webview);
    assert_eq!(history_len(&delegate), 1);
    assert_eq!(webview.url().as_ref(), Some(page));
}

/// Out-of-crate compile pin for the `DownloadRequest` re-export: the
/// delegate overrides above already name the type; this names it
/// directly so a missing re-export fails the build, not just a test.
#[test]
fn download_request_is_reexported() {
    fn _accept(_: Option<servo::DownloadRequest>) {}
}
