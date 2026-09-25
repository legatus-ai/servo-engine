//! Build-time fork checks (invariant 13).
//!
//! A workspace that lacks one of our path patches silently resolves the
//! upstream crate — and still goes green. Doc notes do not prevent that;
//! a failing build does. Each dependency below resolves exactly like
//! every other crate of the same name in the enclosing workspace, so
//! referencing a Legatus-only marker symbol fails to COMPILE against the
//! upstream crate:
//! - `style_traits::legatus_text_overflow_ungated` (sibling `stylo`
//!   branch `legatus`) guards `[patch."https://github.com/servo/stylo"]`.
//! - `url::legatus_opaque_path_trailing_space_encoded` (sibling
//!   `rust-url` branch `legatus`) guards `[patch.crates-io] url`.
//! If you are reading this error: copy the corresponding `[patch]`
//! section from the servo-engine workspace `Cargo.toml` into the
//! workspace you are building.

fn main() {
    assert!(style_traits::legatus_text_overflow_ungated());
    assert!(url::legatus_opaque_path_trailing_space_encoded());
    println!("cargo:rerun-if-changed=build.rs");
}
