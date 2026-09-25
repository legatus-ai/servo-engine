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

#[cfg(test)]
mod tests {
    //! Row #9 regression pin (Ref BRO-53): the decision table row #10's
    //! script-thread changes must not disturb. Pure function — no Servo
    //! instance, runs in the `servo-script` unit suite.

    use super::{DownloadIntent, recognise_download};

    #[test]
    fn attachment_with_filename_is_a_download() {
        assert_eq!(
            recognise_download(
                Some("attachment; filename=\"report.bin\""),
                false,
                "application/octet-stream",
                true,
            ),
            DownloadIntent::Download {
                filename: Some("report.bin".to_owned()),
            }
        );
    }

    #[test]
    fn attachment_without_filename_is_a_download_without_name() {
        assert_eq!(
            recognise_download(Some("attachment"), false, "text/csv", true),
            DownloadIntent::Download { filename: None }
        );
    }

    #[test]
    fn octet_stream_without_disposition_is_a_download() {
        assert_eq!(
            recognise_download(None, false, "application/octet-stream", true),
            DownloadIntent::Download { filename: None }
        );
    }

    #[test]
    fn anchor_download_flag_is_a_download() {
        assert_eq!(
            recognise_download(None, true, "text/html", true),
            DownloadIntent::Download { filename: None }
        );
    }

    #[test]
    fn plain_document_proceeds() {
        assert_eq!(
            recognise_download(None, false, "text/html", true),
            DownloadIntent::Proceed
        );
    }

    #[test]
    fn inline_disposition_proceeds() {
        assert_eq!(
            recognise_download(Some("inline; filename=\"view.html\""), false, "text/html", true),
            DownloadIntent::Proceed
        );
    }

    #[test]
    fn subresource_never_parks() {
        // Attachments and octet-streams below the top-level navigation
        // must not park: only document loads consult the embedder.
        assert_eq!(
            recognise_download(
                Some("attachment; filename=\"report.bin\""),
                false,
                "application/octet-stream",
                false,
            ),
            DownloadIntent::Proceed
        );
    }
}
