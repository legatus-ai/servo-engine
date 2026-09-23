# Design note: park LoadUrl for not-yet-registered browsing contexts (row #10)

Status: proposed, awaiting Vitruvius review. No code.
Amendments (2026-09-23, architect review of d3510ccbb): idle-engine
deadline wait (§3 rewritten, shared with row #9); known-webview
premise verified by citation + pinned by test (§1); superseded loads
logged (§5); test gate cfg-gated (§6); stable failure signature (§4).

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

KNOWN-WEBVIEW PREMISE (verified in code, not assumed):
`handle_new_top_level_browsing_context` inserts the webview into
`self.webviews` synchronously while handling the embedder's
`NewWebView` message (`constellation.rs:3345`); the context itself
registers later, when the session-history commit runs
`new_browsing_context` (`constellation.rs:5519` → insert at
`1195-1196`) after the pipeline/script roundtrip — that roundtrip is
the observed 22 s gap. The constellation handles its receiver FIFO
on one thread (`handle_request`), and the embedder sends `NewWebView`
before any `LoadUrl` for that webview (creation returns the id that
`load` takes), so at any `LoadUrl` in the gap the webview entry
exists. The only window where it does not: `CloseWebView` processed
in between (drop is correct — a closed webview never registers), or
a `LoadUrl` for a never-created id (embedder bug — drop is correct).
Pinned by test: the close-drop unit test (§6d) plus the call-site
guard `self.webviews.contains_key`, which keeps today's
warn-and-drop for both windows.

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

## 3. Bound (both arms, stated) — and it fires on an idle engine

Per-turn sweeping fails exactly when this row matters: the finding's
trace shows the engine going QUIET during the stall, so a sweep that
runs "on every message" never runs and the failure never surfaces —
the same silent failure in a new place. (Row #9 has the identical
limitation today: an idle page with a holding embedder resolves only
on its next event.) One mechanism for both rows, designed once:

- While EITHER parked table is non-empty, the owning event loop
  waits with a deadline instead of blocking forever, then sweeps.
  Constellation (`handle_request`, `constellation.rs:1230-1243`):
  `sel.select()` becomes `sel.select_deadline(earliest)` over the
  pending-load deadlines (crossbeam `Select::select_deadline` — the
  same API the script loop already uses at
  `messaging.rs:508-515`); on timeout, run the expiry sweep (§6c)
  and loop. Script (row-9 retrofit, same branch): `handle_msgs`
  feeds `min(timer_deadline, earliest parked-download deadline)`
  into the existing `select_deadline` wait; the wake with no message
  is harmless (`TimerFired` with no completed timers is already a
  no-op path), and the next turn's `deny_expired_downloads()`
  sweeps as today.
- Ownership stays single: the script owns download-decision expiry
  (after its own wake it notifies the constellation via
  `CancelDownload`, which is why the constellation needs NO sweep
  for `pending_download_decisions`); the constellation owns
  pending-load expiry locally. Pipeline/webview teardown still
  cleans both tables directly, independent of any wake.

- TIME: 30 s from parking. 30 s clears the observed 22 s worst case
  under full load with margin, while failing visibly an order of
  magnitude before a user writes the window off. Open to tuning with
  one more loaded measurement.
- REGISTRATION FAILURE: `CloseWebView` for a webview holding a slot
  drops the slot (a closed webview will never register), as does
  pipeline/webview teardown covering the slot's owner. Both bound
  hits surface the failure below — never a silent warn.

Test for the mechanism (amendment's case): a parked load with zero
other traffic fires its failure within bound + ε, using a short test
deadline — the unit level pins `earliest_deadline` + sweep-on-wake,
the e2e pins the wall-clock bound.

## 4. Embedder-visible failure

`LoadStatus` (`shared/embedder/lib.rs:804`) has no error variant
(Started/HeadParsed/Complete), so `notify_load_status_changed`
cannot express this without extending a `#[repr(i32)]` serialized
enum every embedder matches on — rejected. `notify_crashed` is wrong
semantics (nothing crashed). Proposed, mirroring row #9's additive
pattern: a new `ConstellationToEmbedderMsg::PendingLoadFailed
(webview_id, url, reason)` dispatched in `servo.rs` (ServoUrl →
Url at the boundary, row-9 pattern) to a new defaulted delegate
method with the STABLE signature (Muse #3's item-7 closing step
builds on exactly this — it maps it to a visible Tauri page-load
error):

```rust
fn notify_pending_load_failed(
    &self,
    _webview: WebView,
    _url: Url,
    _reason: PendingLoadFailure,
) {}

pub enum PendingLoadFailure {
    Expired,       // 30 s bound hit, no registration
    WebViewClosed, // close/teardown won the race
}
```

`PendingLoadFailure` lives in `embedder_traits` next to
`LoadStatus`. Default no-op, so existing embedders compile unchanged;
the runtime and pane silently ignore it until they implement it,
which is accepted for this row. The pane records it the way it
records refusals today and can re-issue the navigation itself; that
defensive re-issue stays pane-side and needs architect approval per
the finding — it is NOT part of this row.

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

Superseded loads are logged at `debug!` with both URLs (replaced +
replacement), so a trace shows the drop.

## 6. Tests (red first)

Table + tests live in `servo-constellation-traits`
(`pending_loads` module, pure logic over `UrlRequest`/`WebViewId`/
`Instant` — no constellation instance), run via
`cargo test -p servo-constellation-traits pending`. Enabler: that
crate must compile standalone, which today it does NOT (its
`Zeroize` derives rely on accidental feature unification from
`script_bindings`; bare `-p` fails — proven on pristine HEAD during
row 9). One-line fix rides with this row: `zeroize = { workspace =
true, features = ["zeroize_derive"] }` on that crate's existing dep
(it unconditionally uses the derive; the feature makes it
deterministic instead of accidental).

- Unit (RED: table does not exist): (a) load parked before
  registration commits after it (drain returns the parked request
  once); (b) second LoadUrl replaces the first (last-wins, with the
  debug log); (c) expired deadline yields the failure, not the load;
  (d) close drops the slot and yields the failure; (e)
  `earliest_deadline` over the table drives the §3 wait.
- End-to-end acceptance (harness, needs load-timing control the unit
  level cannot provide): a LoadUrl sent into the registration gap
  commits after registration (no blank window), and a context that
  never registers produces the embedder-visible failure from §4
  within bound + ε on an otherwise idle engine. Deterministic gap
  control is a test-only registration gate, acceptable ONLY behind
  `#[cfg(test)]` (or a test feature): it must not exist in a release
  build, and the note states that as a hard requirement. Without the
  gate the e2e stays load-flaky and the unit tests are the gate.

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
