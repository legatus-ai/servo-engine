# Design note: park LoadUrl for not-yet-registered browsing contexts (row #10)

Status: proposed, awaiting Vitruvius review. No code.

## Evidence (Muse #3, runtime status.md FINDING, 2026-09-23)

Under load, a webview's first navigation never happens and the window
stays blank (~1 run in 10; the user-visible form is a 20 s blank
window). Root cause is observed, not hypothesized: S5's debug log
shows the constellation RECEIVED both LoadUrls and refused them —
`LoadUrl for unknown browsing context` at `05:49:53Z` and `05:49:58Z`
from `constellation.rs:1326`. The top-level context `(0,1)` took 22 s
to register (pipeline creation started `:37`, `Creating new browsing
context` landed `:59`) while both navigations fell in the gap. Nothing
reaches the embedder today, and `WebView::load`
(`webview.rs:529`) is fire-and-forget, so the embedder cannot know.

## 1. Park location

The miss path of the `LoadUrl` arm in
`handle_request_from_embedder` (`constellation.rs:1332-1338`): when
`browsing_contexts.get(&ctx_id)` misses AND the webview itself is
known (`self.webviews` contains it — i.e. `NewWebView` was processed
and only the context registration is outstanding), store the request
instead of warning-and-dropping. If the webview is unknown too
(never created, or already closed), keep today's warn-and-drop: there
is nothing whose registration could drain it.

State: `pending_loads: HashMap<WebViewId, PendingLoad>` on
`Constellation`, where `PendingLoad { url_request (or the derived
LoadData incl. headers), deadline: Instant }`. Keyed by webview — for
top-level loads the context id is `BrowsingContextId::from(webview_id)`
by construction, so one slot per webview is exact. Single-threaded
constellation, so `Instant` is fine (same choice as row #9's parked
table).

SCOPE: top-level `LoadUrl` only. `Reload` for a missing context keeps
its current meaning ("after closure", `handle_reload_msg`) — a reload
carries no URL to park. Subresource and iframe paths never reach this
arm.

## 2. Drain

`new_browsing_context` (`constellation.rs:1195-1196`), immediately
after the `browsing_contexts.insert`, gated on top-level
(`parent_pipeline_id.is_none()`): take the slot for the webview, if
any, and run it through a shared helper used by both the `LoadUrl`
arm and the drain — e.g. `load_top_level_url(webview_id,
url_request)` containing exactly today's arm body (LoadData build +
`load_url(..., NavigationHistoryBehavior::Push, ...)`). One helper,
two callers: the drain cannot diverge from a direct load.

## 3. Bound (both arms, stated)

- TIME: 30 s from parking, checked on every constellation turn/message
  (the row-9 sweep pattern — the constellation has no timers). 30 s
  clears the observed 22 s worst case under full load with margin,
  while failing visibly an order of magnitude before a user writes
  the window off. Open to tuning with one more loaded measurement.
- REGISTRATION FAILURE: `CloseWebView` for a webview holding a slot
  drops the slot (a closed webview will never register), as does
  pipeline/webview teardown covering the slot's owner. Both bound
  hits surface the failure below — never a silent warn.

## 4. Embedder-visible failure

`LoadStatus` (`shared/embedder/lib.rs:804`) has no error variant
(Started/HeadParsed/Complete), so `notify_load_status_changed`
cannot express this without extending a `#[repr(i32)]` serialized
enum every embedder matches on — rejected. `notify_crashed` is wrong
semantics (nothing crashed). Proposed, mirroring row #9's additive
pattern: a new `ConstellationToEmbedderMsg::PendingLoadFailed
(webview_id, url)` dispatched in `servo.rs` to a new defaulted
`WebViewDelegate::notify_pending_load_failed` (default no-op, so
existing embedders compile unchanged). The pane records it the way
it records refusals today and can re-issue the navigation itself;
that defensive re-issue stays pane-side and needs architect approval
per the finding — it is NOT part of this row.

## 5. Ordering: last-wins, single slot

Each `LoadUrl` for an unregistered-but-known webview REPLACES the
slot. Reasoning: the embedder's intent converges (typed-URL-bar
semantics — the last URL is the one the user wants); FIFO would load
a stale page, flash it, then navigate away, doubling history entries
for a document that never existed yet. Against upstream: upstream
Servo has no queue here at all (it drops), so there is no upstream
ordering to preserve; the nearest analog is rapid successive
top-level navigations, where the latest cancels the earlier ones
(pending-changes replacement). Last-wins is that analog, reduced to
one slot because there is no document to preserve between the
queued navigations.

## 6. Tests (red first)

- Unit (new `PendingLoads` table, pure logic, no constellation):
  (a) load parked before registration commits after it (drain returns
  the parked request once); (b) second LoadUrl replaces the first
  (last-wins); (c) expired deadline yields the failure, not the load;
  (d) close drops the slot and yields the failure. RED: table does
  not exist.
- End-to-end acceptance (harness, needs load-timing control the unit
  level cannot provide): a LoadUrl sent into the registration gap
  commits after registration (no blank window), and a context that
  never registers produces the embedder-visible failure from §4.
  Deterministic gap control (e.g. a test-only registration gate) is
  TBD at implementation; without it the e2e stays load-flaky and the
  unit tests are the gate.

## 7. Rejected alternative

Synchronous registration at `NewWebView` (finding's option (c)):
registration completes in `new_browsing_context`, which runs off the
session-history commit after the pipeline/script roundtrip — making
it synchronous blocks the embedder message loop or restructures
pipeline creation. The queue preserves the async architecture (same
shape as row #9's park) for a ~40-line change. Embedded re-issue
(finding's defensive option) is explicitly out: silent engine drop
becomes silent embedder retry-loop risk; the visible failure in §4
is the contract the pane builds on.
