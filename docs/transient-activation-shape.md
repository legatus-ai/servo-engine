# Transient activation — shape note

Status: **scope confirmed, proof GREEN**. Vitruvius confirmed row-11 scope =
(a) positive-activation branch only; duration stays default 5s; no pane flow
depends on sticky. Proof: `components/servo/tests/activation.rs`
(`embedder_input_produces_transient_activation`, GREEN 6.05s, no product
change — the machinery already works end to end).

## Machinery (verified by reading 2026-09-25, proven by test 2026-09-26)

1. **Duration pref**: `dom_transient_activation_duration_ms`, default 5000
   (`components/config/prefs.rs:219-220,488`).

2. **Data model**: `UserActivationTimestamp` — `PositiveInfinity` (initial,
   never activated) / `TimeStamp(CrossProcessInstant)` / `NegativeInfinity`
   (consumed) — `components/script/dom/window/useractivation.rs:101-107`.
   Stored per `Window` as `last_activation_timestamp`.

3. **Queries** (`components/script/dom/window/window.rs`):
   - `has_sticky_activation` (:3846): now >= last timestamp.
   - `has_transient_activation` (:3853): now >= last AND now < last + duration.
   - `consume_last_activation_timestamp` (:3863): -> NegativeInfinity unless
     never-activated.
   - `consume_user_activation` (:3870): early-returns on null navigable;
     TODO (:3879) — wrong when the top-level document is in another
     ScriptThread.

4. **Activation source** (`components/script/dom/event/event.rs`):
   - `dispatch_inner` (:305-321) performs activation notification BEFORE
     dispatch for activation-triggering input events.
   - `is_an_activation_triggering_input_event` (:750-771): trusted-only;
     keydown (non-Esc), mousedown, pointerdown(mouse), pointerup(non-mouse),
     touchend. TODO (:310) on whatwg/html#12126 (meaning of "in a Document").
   - Native path: `handle_native_mouse_button_event`
     (`components/script/dom/document/document_event_handler.rs:893`) builds
     trusted mousedown/mouseup + pointer events (:967-1009, trusted at :1756),
     so embedder-driven trusted native input flows through `dispatch_inner`
     and produces transient activation. Proven by the row-11 test (click and
     keydown phases), not just code-verified.
   - ONLY activation-notification caller in script: `dispatch_inner`.
     Embedder `evaluate_javascript` does NOT signal activation (valid
     control).

5. **Consumers**:
   - execCommand copy/cut/paste: `handle_script_triggered_editing_action`
     (`components/script/dom/document/editing.rs:64-84`) gates clipboard on
     `has_transient_activation`, consumes on change. Copy delivers via
     `EmbedderMsg::SetClipboardText` (script -> constellation -> embedder;
     tests must spin the event loop while awaiting it). Native path
     (`handle_editing_action`, :52) is ungated by design.
   - Fullscreen: requires transient activation, then consumes
     (`components/script/dom/fullscreen/lib.rs:96-116`).
   - `navigator.userActivation`: `UserActivation.webidl`; `HasBeenActive` /
     `IsActive` read sticky/transient (`useractivation.rs:83-95`).

6. **Contract**: `tests/wpt/mozilla/execcommand-copy-security.html` asserts no
   transient activation in the harness and that copy returns false ungated.

## Known gaps (TODOs in-tree, not new findings)

- Close-watcher activation notification not implemented
  (`useractivation.rs:78`).
- Dissimilar-origin ancestor navigables not covered
  (`useractivation.rs:54`).
- `window.open` popup gating NOT implemented: `choose_browsing_context`
  step 8 is `TODO: Implement this`
  (`components/script/dom/window/windowproxy.rs:712-719`). Documented in
  the row-11 test header, not implemented (out of scope).
- `location.rs:89`: history-handling transient-activation check TODO.
- `bluetooth.rs:182`: user-activation trigger TODO.
