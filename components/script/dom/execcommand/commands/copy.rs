/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

use js::context::JSContext;
use script_bindings::codegen::GenericBindings::SelectionBinding::SelectionMethods;

use crate::dom::document::Document;
use crate::dom::selection::Selection;
use crate::dom::text_input::{ClipboardProvider, EmbedderClipboardProvider};

/// <https://w3c.github.io/editing/docs/execCommand/#the-copy-command>
pub(crate) fn execute_copy_command(
    cx: &mut JSContext,
    document: &Document,
    selection: &Selection,
) -> bool {
    let Some(range) = selection.active_range(cx) else {
        return false;
    };
    if range.collapsed() {
        return false;
    }
    let mut clipboard = EmbedderClipboardProvider {
        embedder_sender: document
            .window()
            .as_global_scope()
            .script_to_embedder_chan()
            .clone(),
        webview_id: document.webview_id(),
    };
    clipboard.set_text(selection.Stringifier(cx).to_string());
    true
}
