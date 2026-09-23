/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Row #10 test seam (Ref BRO-53): deterministic registration barrier.
//!
//! Compiled only with the `test-registration-gate` cargo feature, which
//! integration tests enable to open a `LoadUrl` gap on demand: while the
//! gate is armed, the constellation thread blocks inside
//! `new_browsing_context` for a top-level context, so a test can issue a
//! load that parks instead of racing registration. Production builds never
//! contain this module, and a disarmed gate costs one atomic load on the
//! registration path.

use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

/// Whether the next top-level registration must block.
static ARMED: AtomicBool = AtomicBool::new(false);
/// Whether a registration has blocked since the last [`arm`].
static ENTERED: AtomicBool = AtomicBool::new(false);
/// Latch opened by [`release`] that unblocks the waiting registration.
static GATE: (Mutex<bool>, Condvar) = (Mutex::new(false), Condvar::new());

fn lock_gate() -> MutexGuard<'static, bool> {
    GATE
        .0
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Arm the gate: the next top-level `new_browsing_context` blocks until
/// [`release`]. Also clears the [`entered`] flag and closes the latch, so
/// the gate is reusable across tests.
pub fn arm() {
    *lock_gate() = false;
    ENTERED.store(false, Ordering::SeqCst);
    ARMED.store(true, Ordering::SeqCst);
}

/// Whether a registration has blocked since the last [`arm`].
pub fn entered() -> bool {
    ENTERED.load(Ordering::SeqCst)
}

/// Open the latch and disarm, unblocking the waiting registration.
pub fn release() {
    ARMED.store(false, Ordering::SeqCst);
    *lock_gate() = true;
    GATE.1.notify_all();
}

/// Block the constellation thread here while the gate is armed. Called
/// from `new_browsing_context` for top-level contexts only; a no-op (one
/// atomic load) when disarmed.
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
