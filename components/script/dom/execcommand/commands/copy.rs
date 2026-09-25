/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

use embedder_traits::{EditingActionEvent, InputEventResult};
use js::context::JSContext;
use script_bindings::codegen::GenericBindings::RangeBinding::RangeMethods;
use script_bindings::codegen::GenericBindings::SelectionBinding::SelectionMethods;

use crate::dom::document::Document;
use crate::dom::selection::Selection;

/// <https://w3c.github.io/editing/docs/execCommand/#the-copy-command> and
/// <https://www.w3.org/TR/clipboard-apis/#clipboard-actions>.
///
/// Runs through the clipboard-apis machinery so the page's `copy`
/// ClipboardEvent fires first with a ReadWrite clipboardData; if the page
/// calls preventDefault(), the DataTransfer items land on the clipboard,
/// otherwise the selection text is written. Clipboard access requires
/// transient user activation: without it, nothing is written and no event
/// fires (Legatus security: scripts must not silently overwrite the OS
/// clipboard). A selection inside `<input type=password>` is never copied
/// from the script path.
pub(crate) fn execute_copy_command(
    cx: &mut JSContext,
    document: &Document,
    selection: &Selection,
) -> bool {
    // A live range is required; on a collapsed range there is nothing to
    // copy and other browsers return false.
    let Some(range) = selection.active_range(cx) else {
        return false;
    };
    if range.collapsed() {
        return false;
    }

    let start_container = range.start_container();
    let result = document
        .handle_script_triggered_editing_action(cx, &start_container, EditingActionEvent::Copy);
    result.intersects(InputEventResult::Consumed | InputEventResult::DefaultPrevented)
}
