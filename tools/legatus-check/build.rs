//! Build-time Stylo fork check (follow-up 2).
//!
//! A downstream workspace that lacks the Stylo path patch silently resolves
//! upstream Stylo — where `text-overflow` is still gated behind
//! `layout.unimplemented` — and still goes green. Doc notes do not prevent
//! that; a failing build does. `stylo_traits` here resolves exactly like
//! every other Stylo crate in the enclosing workspace, so referencing the
//! Legatus-only marker symbol `legatus_text_overflow_ungated` (added in the
//! sibling `stylo` branch `legatus`) fails to COMPILE against upstream
//! Stylo. If you are reading this error: add the
//! `[patch."https://github.com/servo/stylo"]` section from the
//! servo-engine workspace `Cargo.toml` to the workspace you are building.

fn main() {
    assert!(style_traits::legatus_text_overflow_ungated());
    println!("cargo:rerun-if-changed=build.rs");
}
