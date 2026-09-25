/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

use js::context::JSContext;
use script_bindings::codegen::GenericBindings::DocumentBinding::DocumentMethods;
use script_bindings::codegen::GenericBindings::RangeBinding::RangeMethods;
use script_bindings::codegen::GenericBindings::SelectionBinding::SelectionMethods;

use crate::dom::bindings::root::DomRoot;
use crate::dom::document::Document;
use crate::dom::node::Node;
use crate::dom::selection::Selection;

/// <https://w3c.github.io/editing/docs/execCommand/#the-selectall-command>
pub(crate) fn execute_select_all_command(
    cx: &mut JSContext,
    document: &Document,
    selection: &Selection,
) -> bool {
    // Select the editing host containing the range; with no range (or no
    // host, e.g. a plain document) select the document element instead,
    // matching other browsers.
    let target: Option<DomRoot<Node>> = selection
        .active_range(cx)
        .and_then(|range| range.start_container().editing_host_of())
        .or_else(|| {
            document
                .GetDocumentElement()
                .map(DomRoot::upcast::<Node>)
        });
    let Some(target) = target else {
        return false;
    };
    selection.SelectAllChildren(cx, &target).is_ok()
}
