/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Parked `LoadUrl`s for known-but-unregistered top-level browsing
//! contexts (row #10, Ref BRO-53).
//!
//! Pure table over `UrlRequest`/`WebViewId`/`Instant` — no
//! constellation instance. Park/drain wiring lives in the
//! constellation; the red-first tests below cover the table.

use std::collections::HashMap;
use std::time::Instant;

use embedder_traits::UrlRequest;
use servo_base::id::WebViewId;

/// A `LoadUrl` parked while its top-level browsing context is not yet
/// registered. Drained on registration, failed visibly on the bound.
#[derive(Debug)]
pub struct PendingLoad {
    pub request: UrlRequest,
    pub deadline: Instant,
}

/// One slot per webview (context id derives from the webview id for
/// top-level loads, so a single slot is exact). Last-wins: each new
/// `LoadUrl` replaces the parked one.
#[derive(Debug, Default)]
pub struct PendingLoads {
    inner: HashMap<WebViewId, PendingLoad>,
}

impl PendingLoads {
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Park a load, replacing any earlier one. The replacement keeps the
    /// ORIGINAL deadline: a fresh bound per replacement would let a
    /// stuck page defer expiry forever under steady traffic.
    /// Returns the replaced load so the caller can log both URLs at debug.
    pub fn insert(
        &mut self,
        webview_id: WebViewId,
        request: UrlRequest,
        deadline: Instant,
    ) -> Option<PendingLoad> {
        let deadline = self
            .inner
            .get(&webview_id)
            .map_or(deadline, |existing| existing.deadline);
        self.inner
            .insert(webview_id, PendingLoad { request, deadline })
    }

    /// Drain on registration. Yields the load at most once.
    pub fn take_for_registration(&mut self, webview_id: WebViewId) -> Option<PendingLoad> {
        self.inner.remove(&webview_id)
    }

    /// Drop on close/teardown. The caller surfaces the failure.
    pub fn remove(&mut self, webview_id: WebViewId) -> Option<PendingLoad> {
        self.inner.remove(&webview_id)
    }

    /// Remove every parked load without reporting. Used on shutdown
    /// (`handle_exit`), where the teardown would otherwise expire the
    /// slots one by one and emit failure noise for loads that simply
    /// never got a page.
    pub fn clear(&mut self) {
        self.inner.clear();
    }

    /// Sweep past-due loads. Returned loads must surface as failures,
    /// never load.
    pub fn expired(&mut self, now: Instant) -> Vec<(WebViewId, PendingLoad)> {
        let due: Vec<WebViewId> = self
            .inner
            .iter()
            .filter(|(_, parked)| parked.deadline <= now)
            .map(|(id, _)| *id)
            .collect();
        due.into_iter()
            .filter_map(|id| self.inner.remove(&id).map(|parked| (id, parked)))
            .collect()
    }

    /// Earliest deadline in the table. Drives the deadline-wait (§3 of
    /// the design note): the event loop waits until at most this
    /// instant while the table is non-empty, then sweeps.
    pub fn earliest_deadline(&self) -> Option<Instant> {
        self.inner.values().map(|parked| parked.deadline).min()
    }
}

#[cfg(test)]
mod tests {
    use embedder_traits::UrlRequest;
    use http::HeaderMap;
    use servo_base::id::{
        PIPELINE_NAMESPACE, BrowsingContextId, PipelineNamespace, PipelineNamespaceId, WebViewId,
    };
    use servo_url::ServoUrl;
    use std::time::{Duration, Instant};

    use super::PendingLoads;

    fn install_test_namespace() {
        if PIPELINE_NAMESPACE.get().is_none() {
            PipelineNamespace::install(PipelineNamespaceId(1));
        }
    }

    fn webview() -> WebViewId {
        install_test_namespace();
        WebViewId::mock_for_testing(BrowsingContextId::new())
    }

    fn request(url: &str) -> UrlRequest {
        UrlRequest {
            url: ServoUrl::parse(url).unwrap(),
            headers: HeaderMap::new(),
        }
    }

    #[test]
    fn parked_load_drains_once_on_registration() {
        let mut table = PendingLoads::default();
        let id = webview();
        table.insert(id, request("https://example.com/a"), Instant::now());
        let taken = table
            .take_for_registration(id)
            .expect("parked load must drain on registration");
        assert_eq!(taken.request.url.as_str(), "https://example.com/a");
        assert!(table.take_for_registration(id).is_none());
        assert!(table.is_empty());
    }

    #[test]
    fn second_load_replaces_first() {
        let mut table = PendingLoads::default();
        let id = webview();
        table.insert(id, request("https://example.com/stale"), Instant::now());
        let replaced = table.insert(id, request("https://example.com/fresh"), Instant::now());
        let old = replaced.expect("replaced load must come back for the debug log");
        assert_eq!(old.request.url.as_str(), "https://example.com/stale");
        let taken = table.take_for_registration(id).unwrap();
        assert_eq!(taken.request.url.as_str(), "https://example.com/fresh");
    }

    #[test]
    fn replacing_keeps_original_deadline() {
        // Row 10 review: an embedder retrying more often than the bound
        // must still see a failure — a replacement must not push the
        // deadline out, or the silent loop from §7 never surfaces.
        let mut table = PendingLoads::default();
        let id = webview();
        let first_deadline = Instant::now() + Duration::from_secs(30);
        table.insert(
            id,
            request("https://example.com/stale"),
            first_deadline,
        );
        table.insert(
            id,
            request("https://example.com/fresh"),
            Instant::now() + Duration::from_secs(60),
        );
        assert_eq!(table.earliest_deadline(), Some(first_deadline));
        let taken = table.take_for_registration(id).unwrap();
        assert_eq!(taken.request.url.as_str(), "https://example.com/fresh");
    }

    #[test]
    fn expired_deadline_yields_failure_not_load() {
        let mut table = PendingLoads::default();
        let id = webview();
        table.insert(id, request("https://example.com/slow"), Instant::now());
        let expired = table.expired(Instant::now() + Duration::from_secs(31));
        assert_eq!(expired.len(), 1);
        assert_eq!(expired[0].0, id);
        assert_eq!(
            expired[0].1.request.url.as_str(),
            "https://example.com/slow"
        );
        assert!(table.is_empty());
        assert!(table.take_for_registration(id).is_none());
    }

    #[test]
    fn close_drops_slot() {
        let mut table = PendingLoads::default();
        let id = webview();
        table.insert(id, request("https://example.com/doomed"), Instant::now());
        let dropped = table.remove(id).expect("close must drop the slot");
        assert_eq!(dropped.request.url.as_str(), "https://example.com/doomed");
        assert!(table.is_empty());
    }

    #[test]
    fn earliest_deadline_drives_the_wait() {
        let mut table = PendingLoads::default();
        assert!(table.earliest_deadline().is_none());
        let now = Instant::now();
        let first = webview();
        let second = webview();
        table.insert(
            first,
            request("https://example.com/a"),
            now + Duration::from_secs(30),
        );
        table.insert(
            second,
            request("https://example.com/b"),
            now + Duration::from_secs(10),
        );
        assert_eq!(
            table.earliest_deadline(),
            Some(now + Duration::from_secs(10))
        );
        table.remove(second);
        assert_eq!(
            table.earliest_deadline(),
            Some(now + Duration::from_secs(30))
        );
    }
}
