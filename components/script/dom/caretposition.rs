/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

use dom_struct::dom_struct;
use js::context::JSContext;
use js::rust::HandleObject;
use script_bindings::reflector::{Reflector, reflect_dom_object_with_proto};

use crate::dom::bindings::codegen::Bindings::CaretPositionBinding::CaretPositionMethods;
use crate::dom::bindings::root::{Dom, DomRoot};
use crate::dom::globalscope::GlobalScope;
use crate::dom::node::Node;

/// <https://drafts.csswg.org/cssom-view/#caretposition>
#[dom_struct]
pub(crate) struct CaretPosition {
    reflector_: Reflector,
    offset_node: Dom<Node>,
    offset: u32,
}

impl CaretPosition {
    fn new_inherited(offset_node: &Node, offset: u32) -> CaretPosition {
        CaretPosition {
            reflector_: Reflector::new(),
            offset_node: Dom::from_ref(offset_node),
            offset,
        }
    }

    pub(crate) fn new(
        cx: &mut JSContext,
        global: &GlobalScope,
        proto: Option<HandleObject>,
        offset_node: &Node,
        offset: u32,
    ) -> DomRoot<CaretPosition> {
        reflect_dom_object_with_proto(
            cx,
            Box::new(CaretPosition::new_inherited(offset_node, offset)),
            global,
            proto,
        )
    }
}

impl CaretPositionMethods<crate::DomTypeHolder> for CaretPosition {
    /// <https://drafts.csswg.org/cssom-view/#dom-caretposition-offsetnode>
    fn OffsetNode(&self) -> DomRoot<Node> {
        DomRoot::from_ref(&*self.offset_node)
    }

    /// <https://drafts.csswg.org/cssom-view/#dom-caretposition-offset>
    fn Offset(&self) -> u32 {
        self.offset
    }
}
