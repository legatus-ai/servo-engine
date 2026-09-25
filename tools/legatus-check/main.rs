//! Legatus standalone build gate (see docs/upstream-and-scorecard.md).
//!
//! This binary exists so every upstream sync can verify the engine on its
//! own: `cargo check -p legatus-check` compiles the three engine crates our
//! Legatus patches touch (`script`, `layout`, `fonts`) under this
//! workspace's stylo `[patch]`, without needing servoshell, resources, or
//! any downstream manifest. The gate is compilation itself: our patches'
//! APIs (`process_text_rects_request`, `select_word_at_dom_position`,
//! `synthesize_presentational_hints`, the ellipsis hook) are mostly
//! `pub(crate)`, so an upstream refactor that moves or renames them fails
//! right here instead of silently changing behavior downstream.

fn main() {
    println!("legatus-check ok");
}
