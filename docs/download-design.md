# Design note: refuse downloads in browse mode (row #9)

Status: proposed, awaiting Vitruvius review. No code.

## Problem

Pane conformance `browse-download-denied` fails on the fork: fetching a
`Content-Disposition: attachment` response navigates the webview away
(page A lost, `#fill` gone), which also aborts the six pivot/home rows
behind it in `browse()`. Same failure exists upstream — libservo 0.5.0's
`WebViewDelegate` has navigation/unload/move/resize/protocol/create-new
hooks and nothing for downloads; constellation and net contain zero
download handling (only a fetch `Initiator::Download` enum variant).
Our fork is identical. No embedder code can answer "deny" today.

## 1. Detection

At `ScriptThread::handle_fetch_metadata` (`components/script/event_loop/
script_thread.rs:4059`) the full response headers are available
(`Metadata.headers`, `shared/net/lib.rs:1088`) and NO document work has
happened yet — `Document::new` for the navigation runs later in the
`load()`-family path (~line 3550), and session history commits after
that. So metadata time is before page-A teardown by construction.

Recognise a download when ANY holds (narrow by default; wider MIME
sniffing is a recorded follow-up, not this row):

- `Content-Disposition: attachment` (parse via the `headers` crate,
  same `typed_get` pattern the code already uses for `LastModified`
  two lines above the hook point), filename from its `filename`/
  `filename*` parameter when present;
- the navigation carries the download flag from an `<a download>`
  anchor (currently unimplemented upstream: `htmlanchorelement.rs:385`
  `TODO: Download the link is 'download' attribute is set` — thread it
  by marking the navigation/fetch request at the `follow_hyperlink`
  call site, carried as the request initiator to metadata time);
- `application/octet-stream` content type.

SCOPE: top-level and iframe navigations only (destination Document /
frame loads). Subresource fetches (`fetch()`, XHR, `<img>`) are NEVER
downloads however their MIME reads — gate on the load destination at
the hook point. An iframe download reports to the TOP-LEVEL webview's
delegate (WebViewDelegate is per-webview), carrying the initiating
frame's URL in the request so the embedder can tell which frame asked.

## 2. Delegate API

One new `WebViewDelegate` method, mirroring `NavigationRequest`:

```rust
fn request_download(&self, _webview: WebView, request: DownloadRequest) {}

pub struct DownloadRequest {
    pub url: ServoUrl,
    pub frame_url: Option<ServoUrl>, // initiating frame, if not top-level
    pub suggested_filename: Option<String>,
    pub mime: Option<String>,
    pub size_hint: Option<u64>, // from Content-Length when present
}
impl DownloadRequest {
    pub fn allow(self, path: PathBuf); // out of scope for now, see §4
    pub fn deny(self);
}
impl Drop for DownloadRequest {
    // Fail closed: an embedder that never answers (including every
    // existing embedder, which does not implement the method) denies
    // and keeps page A. NOTE this is the opposite default from
    // NavigationRequest::drop (which allows); downloads fail closed
    // deliberately, mirroring the runtime's origin boundary.
}
```

Message path, mirroring `NavigationRequest::allow/deny`
(`webview_delegate.rs:41-69`): the request carries a
`ConstellationProxy` + id and answers via
`EmbedderToConstellationMessage`, so it works in-process and across
processes unchanged.

PARKED, NOT BLOCKED. The decision happens in the script thread; the
delegate lives with the embedder. On trigger, script holds the
`FetchMetadata`, creates no document, and stops the body from
accumulating (chunks arriving before the answer are dropped, not
buffered — Allow is out of scope, so no bytes ever need keeping).
It then returns to its loop. It MUST NOT wait on the embedder: an
embedder pumping its own loop while script waits is a deadlock (the
runtime hit exactly this ordering class in its item 1).

TIMEOUT: every parked load carries a deadline (propose 10s; exact
mechanism — per-turn check vs oneshot timer — at implementation). If no
answer arrives, script denies and cancels the fetch itself. A request
object that is never dropped must not hang page A's navigation: the
deadline, not the Drop, is the backstop.

CANCEL: deny (explicit or timeout) cancels the network load via the
existing path — `cancel_async_fetch(request_ids, …)`
(`shared/net/lib.rs:1060`) — so bytes stop arriving.

Backward compatibility falls out of Rust defaults: a trait method with
a default no-op body compiles unchanged for every existing implementor
(pane renderer, servoshell, probe). The pane answers Deny in browse
mode (recording it in `blocked`, like refusals today) and can later
answer Allow(path) behind a user gesture.

## 3. Cancel-before-teardown (the row's acceptance)

Denying at metadata time prevents `Document::new` and the history
commit, so page A — and `#fill`, and the six pivot rows behind it —
survives intact. Acceptance: conformance `browse-download-denied`
passes (title still `A`, `blocked` contains the download) AND the
pivot/home rows execute again. The script-thread side must also drop
the in-flight fetch (cancel the pipeline's network load) so bytes stop
arriving; the document loader's existing cancellation path covers it
once the navigation is denied rather than committed.

## 4. Out of scope

Actually writing files (Allow path, picker UI, progress, completion
events) is a later row. Deny-only closes the pane's gap: browse mode
never wants the bytes.

## 5. Tests

- Unit/WPT-style test serving an attachment (same shape as the
  conformance `/file` route): assert no navigation occurred (title
  unchanged, `#fill` present) and exactly one delegate call with the
  expected filename/MIME.
- Timeout test: delegate never answers → denied at the deadline, page A
  intact, fetch cancelled.
- Iframe-attachment test: attachment navigation inside an iframe →
  reported to the top-level webview's delegate with the frame URL.
- Re-run pane conformance both arms: the 6 pivot/home rows get measured
  for the first time on the fork (they currently abort), and
  `browse-download-denied` must flip to pass.

## 6. Upstream suitability

A trait method with a default body + a drop-denies request object is
the shape upstream takes without breaking embedders (it mirrors how
`request_navigation`/`request_create_new` already work). If Gary wants
it contributed, the commit should be the API + deny path only, with
the Legatus-specific bits (blocked-list wording, conformance rows) kept
out. Note: the pane's r24 binary builds the fork at the pinned rev, so
whatever lands here must be in our `legatus` branch (and the pin
advanced) before the pane can use it.
