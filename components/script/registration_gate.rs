/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row #10 test seam (Ref BRO-53): deterministic registration barrier.
//!
//! Compiled only with the `test-registration-gate` cargo feature, which
//! integration tests enable to hold a top-level registration open on
//! demand: while the gate is armed, the script thread blocks just before
//! sending `ActivateDocument`, so the browsing context never registers
//! while the constellation thread stays free — a test's `LoadUrl` parks
//! instead of racing registration, and `close()` plus expiry still
//! interleave with the held-open gap. Production builds never contain
//! this module, and a disarmed gate costs one atomic load on the
//! activation path.
//!
//! Tests using the gate must serialize on a mutex (the statics are
//! process-global) and must always [`release`] — preferably via a
//! drop-guard — or the blocked pipeline stalls shutdown.

use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

/// Whether the next activation must block.
static ARMED: AtomicBool = AtomicBool::new(false);
/// Whether an activation has blocked since the last [`arm`].
static ENTERED: AtomicBool = AtomicBool::new(false);
/// Latch opened by [`release`] that unblocks the waiting activation.
static GATE: (Mutex<bool>, Condvar) = (Mutex::new(false), Condvar::new());

fn lock_gate() -> MutexGuard<'static, bool> {
    GATE
        .0
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Arm the gate: the next `ActivateDocument` send blocks until
/// [`release`]. Also clears the [`entered`] flag and closes the latch,
/// so the gate is reusable across tests.
pub fn arm() {
    *lock_gate() = false;
    ENTERED.store(false, Ordering::SeqCst);
    ARMED.store(true, Ordering::SeqCst);
}

/// Whether an activation has blocked since the last [`arm`].
pub fn entered() -> bool {
    ENTERED.load(Ordering::SeqCst)
}

/// Open the latch and disarm, unblocking the waiting activation.
pub fn release() {
    ARMED.store(false, Ordering::SeqCst);
    *lock_gate() = true;
    GATE.1.notify_all();
}

/// Block the script thread here while the gate is armed. Called just
/// before sending `ActivateDocument`; a no-op (one atomic load) when
/// disarmed.
pub(crate) fn wait_if_armed() {
    if !ARMED.load(Ordering::SeqCst) {
        return;
    }
    ENTERED.store(true, Ordering::SeqCst);
    let mut open = lock_gate();
    while !*open {
        open = GATE
            .1
            .wait(open)
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    }
}
