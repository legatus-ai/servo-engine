/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Red-first tests for row #9 (Ref BRO-53): download recognition for
//! browse-mode refusal. The decision is a pure function over the already
//! parsed inputs (header parsing stays at the call site), so it is tested
//! without a script thread; the park/timeout/cancel machinery is covered
//! by the pane conformance row `browse-download-denied` (the pane never
//! answers, so every run exercises timeout→deny) plus a WPT iframe case.

use script::download_decision::{DownloadIntent, recognise_download};

#[test]
fn attachment_header_is_a_download() {
    let intent = recognise_download(
        Some("attachment; filename=\"report.bin\""),
        false,
        "application/octet-stream",
        true,
    );
    assert!(matches!(intent, DownloadIntent::Download { .. }));
}

#[test]
fn anchor_download_flag_is_a_download() {
    let intent = recognise_download(Some("inline"), true, "text/html", true);
    assert!(matches!(intent, DownloadIntent::Download { .. }));
}

#[test]
fn octet_stream_is_a_download() {
    let intent = recognise_download(None, false, "application/octet-stream", true);
    assert!(matches!(intent, DownloadIntent::Download { .. }));
}

#[test]
fn plain_html_page_is_not_a_download() {
    assert_eq!(
        recognise_download(None, false, "text/html", true),
        DownloadIntent::Proceed
    );
}

#[test]
fn subresource_fetch_is_never_a_download() {
    // Even an attachment-looking response to fetch()/XHR/img stays a
    // subresource load: only top-level and frame navigations download.
    assert_eq!(
        recognise_download(Some("attachment"), true, "application/octet-stream", false),
        DownloadIntent::Proceed
    );
}

#[test]
fn inline_disposition_is_not_a_download() {
    assert_eq!(
        recognise_download(Some("inline"), false, "text/html", true),
        DownloadIntent::Proceed
    );
}
