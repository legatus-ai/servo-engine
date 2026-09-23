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

/// Records history commits and download requests.
#[derive(Default)]
struct RecordingDelegate {
    history: RefCell<Vec<Url>>,
    downloads: RefCell<Vec<(Url, Option<String>)>>,
}

impl WebViewDelegate for RecordingDelegate {
    fn notify_history_changed(&self, _webview: WebView, entries: Vec<Url>, current: usize) {
        if let Some(url) = entries.get(current).cloned() {
            self.history.borrow_mut().push(url);
        }
    }

    fn notify_url_changed(&self, _webview: WebView, _url: Url) {}

    fn request_download(&self, _webview: WebView, request: DownloadRequest) {
        self.downloads.borrow_mut().push((
            request.url.clone(),
            request.suggested_filename.clone(),
        ));
        // Drop without answering: the default, which denies and keeps
        // the current page.
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
</body></html>"#;

/// Serve the page, an attachment octet-stream at /file, and a plain
/// text (non-attachment) response at /notes.
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
                    response.headers_mut().insert(
                        "content-type",
                        HeaderValue::from_static("text/plain"),
                    );
                    *response.body_mut() = make_body(b"just notes".to_vec());
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

/// The r27 case: `<a download>` to an attachment octet-stream.
/// The page must be kept and `request_download` must fire with the
/// attachment's filename.
#[test]
fn anchor_download_attribute_with_attachment_headers_downloads() {
    let servo_test = ServoTest::new();
    let delegate = Rc::new(RecordingDelegate::default());
    let (server, page) = serve_test_site();
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

    let _ = server.close();
}

/// Header alone triggers: a plain link (no `download` attribute) to an
/// attachment response is still a download, not a navigation.
#[test]
fn plain_link_to_attachment_headers_downloads() {
    let servo_test = ServoTest::new();
    let delegate = Rc::new(RecordingDelegate::default());
    let (server, page) = serve_test_site();
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

    let _ = server.close();
}

/// Attribute alone triggers: `<a download>` to a same-origin
/// non-attachment response is a download, not a navigation.
#[test]
fn anchor_download_attribute_to_plain_response_downloads() {
    let servo_test = ServoTest::new();
    let delegate = Rc::new(RecordingDelegate::default());
    let (server, page) = serve_test_site();
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

    let _ = server.close();
}

/// Out-of-crate compile pin for the `DownloadRequest` re-export: the
/// delegate overrides above already name the type; this names it
/// directly so a missing re-export fails the build, not just a test.
#[test]
fn download_request_is_reexported() {
    fn _accept(_: Option<servo::DownloadRequest>) {}
}
