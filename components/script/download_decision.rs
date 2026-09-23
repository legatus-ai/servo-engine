/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Download recognition for browse-mode refusal (row #9, Ref BRO-53).
//!
//! Pure decision function over already-parsed inputs; header parsing
//! stays at the call site (`ScriptThread::handle_fetch_metadata`).

/// What a navigation response is: either proceed with document load or
/// treat it as a download (deny in browse mode, fail closed).
#[derive(Clone, Debug, PartialEq)]
pub enum DownloadIntent {
    Proceed,
    Download { filename: Option<String> },
}

/// Decide whether a navigation response is a download.
///
/// - `content_disposition`: the raw `Content-Disposition` header value, if any.
/// - `anchor_download`: the navigation came from an `<a download>` link.
/// - `mime Essence`: lowercased `type/subtype` of the response.
/// - `is_navigation`: top-level or frame navigation (never a subresource).
pub fn recognise_download(
    content_disposition: Option<&str>,
    anchor_download: bool,
    mime_essence: &str,
    is_navigation: bool,
) -> DownloadIntent {
    if !is_navigation {
        return DownloadIntent::Proceed;
    }
    if let Some(disposition) = content_disposition {
        let kind = disposition.split(';').next().unwrap_or("").trim();
        if kind.eq_ignore_ascii_case("attachment") {
            return DownloadIntent::Download {
                filename: attachment_filename(disposition),
            };
        }
    }
    if anchor_download || mime_essence.eq_ignore_ascii_case("application/octet-stream") {
        return DownloadIntent::Download { filename: None };
    }
    DownloadIntent::Proceed
}

/// Extract `filename`/`filename*` from a `Content-Disposition` value.
/// Keeps it simple and syntactic; RFC 2231 continuations are out of scope.
fn attachment_filename(disposition: &str) -> Option<String> {
    for part in disposition.split(';').skip(1) {
        let part = part.trim();
        if let Some(value) = part
            .strip_prefix("filename*=")
            .or_else(|| part.strip_prefix("filename="))
        {
            let value = value.trim().trim_matches('"').trim().to_owned();
            if !value.is_empty() {
                return Some(value);
            }
        }
    }
    None
}
