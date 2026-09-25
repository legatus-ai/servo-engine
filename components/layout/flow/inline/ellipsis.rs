/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

//! Single-line `text-overflow: ellipsis` (Legatus #7, phase 1).
//!
//! After [`super::LineItemLayout::layout_line_items`] turns a line's items
//! into [`Fragment`]s (in visual order), lines whose content overflows the
//! available inline size are truncated from the logical-end side and given
//! a trailing ellipsis fragment. See `docs/ellipsis-design.md`.

use std::sync::Arc;

use app_units::Au;
use fonts::{
    FontContext, FontRef, ShapedTextSlice, ShapedTextSliceType, ShapedTextSlicer, ShapingFlags,
    ShapingOptions,
};
use icu_locale_core::subtags::Language;
use servo_base::text::Utf32CodeUnits;
use style::computed_values::font_variant_position::T as FontVariantPosition;
use style::properties::ComputedValues;
use style::values::computed::box_::Overflow;
use style::values::computed::text::TextOverflow;
use style::values::computed::{
    FontFeatureSettings, FontVariantEastAsian, FontVariantLigatures, FontVariantNumeric,
};
use style::values::specified::text::TextOverflowSide;
use style::Zero;
use unicode_script::Script;

use crate::context::LayoutContext;
use crate::fragment_tree::{BaseFragment, BaseFragmentInfo, Fragment, TextFragment};

/// Saturating subtraction for [`Au`] (which has no saturating ops).
fn sat_sub(a: Au, b: Au) -> Au {
    if b > a {
        Au::zero()
    } else {
        a - b
    }
}

/// The ellipsis marker: U+2026, with a "..." fallback when the block font
/// lacks the glyph.
const ELLIPSIS_MARKERS: [&str; 2] = ["\u{2026}", "..."];

/// Whether this line wants phase-1 ellipsis truncation: single logical-end
/// `ellipsis` (two-value physical sides and `<string>` are phase 2) on a
/// block whose inline-axis overflow is `hidden` or `clip` (`visible` gets
/// no ellipsis; `scroll`/`auto` need scroll-aware truncation, phase 2).
fn ellipsis_end_style(block_style: &ComputedValues) -> bool {
    let text_overflow: &TextOverflow = &block_style.get_text().text_overflow;
    if !text_overflow.sides_are_logical {
        return false;
    }
    if !matches!(text_overflow.second, TextOverflowSide::Ellipsis) {
        return false;
    }
    matches!(
        block_style.get_box().overflow_x,
        Overflow::Hidden | Overflow::Clip
    )
}

/// Shape the ellipsis marker with the block container's font, falling back
/// to "..." when U+2026 is missing. Returns the shaping font, the shaped
/// slices and their total advance, or `None` when no font can shape a
/// marker at all (then the line is clipped without a marker).
fn shape_ellipsis(
    block_style: &ComputedValues,
    font_context: &FontContext,
) -> Option<(FontRef, Vec<Arc<ShapedTextSlice>>, Au)> {
    let font_style = block_style.clone_font();
    let language = font_style._x_lang.0.parse().unwrap_or(Language::UNKNOWN);
    let font_group = font_context.font_group(font_style);
    let options = ShapingOptions {
        letter_spacing: Au::zero(),
        word_spacing: Au::zero(),
        script: Script::Common,
        language,
        ligatures: FontVariantLigatures::NORMAL,
        numeric: FontVariantNumeric::NORMAL,
        east_asian: FontVariantEastAsian::NORMAL,
        feature_settings: FontFeatureSettings::normal(),
        position: FontVariantPosition::Normal,
        flags: ShapingFlags::empty(),
        alternates: Default::default(),
    };
    for marker in ELLIPSIS_MARKERS {
        let Some(first_char) = marker.chars().next() else {
            continue;
        };
        let Some(font) = font_group.find_by_codepoint(font_context, first_char, None, language)
        else {
            continue;
        };
        if !font.has_glyph_for(first_char) {
            continue;
        }
        let shaped = font.shape_text(marker, &options);
        let char_count = Utf32CodeUnits(marker.chars().count() as u32);
        let Some(slice) = ShapedTextSlicer::new(shaped)
            .slice_until_character_offset(char_count, ShapedTextSliceType::Word)
        else {
            continue;
        };
        let advance = slice.total_advance();
        if advance.is_zero() {
            continue;
        }
        return Some((font, vec![slice], advance));
    }
    None
}

/// Inline size of in-flow content: text glyph advances plus atomic box
/// widths. Floats and out-of-flow fragments do not consume line space.
fn content_inline_size(fragments: &[Fragment]) -> Au {
    fragments
        .iter()
        .map(|fragment| match fragment {
            Fragment::Text(text) => text
                .glyphs
                .iter()
                .map(|slice| slice.total_advance())
                .sum(),
            Fragment::Box(box_fragment) => box_fragment.base.rect().size.width,
            _ => Au::zero(),
        })
        .sum()
}

/// Advance of the leading `count` physical glyphs of `slice`.
fn leading_glyph_advance(slice: &ShapedTextSlice, count: usize) -> Au {
    slice.glyphs().take(count).map(|glyph| glyph.advance()).sum()
}

/// Advance of the trailing `count` physical glyphs of `slice`.
fn trailing_glyph_advance(slice: &ShapedTextSlice, count: usize) -> Au {
    let total = slice.glyph_count();
    slice
        .glyphs()
        .skip(total.saturating_sub(count))
        .map(|glyph| glyph.advance())
        .sum()
}

/// Leading physical glyphs of `slice` to keep so their advance fits
/// `max_advance`, adjusted so the cut never strands a zero-character
/// continuation glyph (combining mark, ZWJ sequence part) on the drained
/// side without its base, and never splits a multi-character ligature.
fn keep_leading_glyphs_for_advance(slice: &ShapedTextSlice, max_advance: Au) -> usize {
    let glyphs: Vec<_> = slice.glyphs().collect();
    let mut advance = Au::zero();
    let mut keep = 0;
    for (index, glyph) in glyphs.iter().enumerate() {
        if advance + glyph.advance() > max_advance {
            break;
        }
        advance += glyph.advance();
        keep = index + 1;
    }
    while keep < glyphs.len() && glyphs[keep].character_count().0 == 0 {
        keep = keep.saturating_sub(1);
        if keep == 0 {
            break;
        }
    }
    keep
}

/// Mirror of [`keep_leading_glyphs_for_advance`] for truncating the
/// physical start: trailing physical glyphs to keep.
fn keep_trailing_glyphs_for_advance(slice: &ShapedTextSlice, max_advance: Au) -> usize {
    let glyphs: Vec<_> = slice.glyphs().collect();
    let mut advance = Au::zero();
    let mut keep = 0;
    for (index, glyph) in glyphs.iter().enumerate().rev() {
        if advance + glyph.advance() > max_advance {
            break;
        }
        advance += glyph.advance();
        keep = glyphs.len() - index;
    }
    while keep < glyphs.len() && glyphs[glyphs.len() - keep].character_count().0 == 0 {
        keep = keep.saturating_sub(1);
        if keep == 0 {
            break;
        }
    }
    keep
}

/// Split one [`TextFragment`]'s glyphs so `free` advance is released,
/// cutting from the physical end (`from_end`) or start. Whole slices go
/// first; the straddling slice is split at a cluster-clean glyph boundary.
/// Returns the kept slices (in order) and the advance actually freed; the
/// kept list may be empty.
fn truncate_text_glyphs(
    text: &TextFragment,
    free: Au,
    from_end: bool,
) -> (Vec<Arc<ShapedTextSlice>>, Au) {
    let original_advance: Au = text
        .glyphs
        .iter()
        .map(|slice| slice.total_advance())
        .sum();
    let keep_target = sat_sub(original_advance, free);
    let mut kept_slices = Vec::new();
    let mut kept_advance = Au::zero();
    let mut stopped = false;
    // Physical iteration order from the kept side.
    let mut ordered: Vec<&Arc<ShapedTextSlice>> = text.glyphs.iter().collect();
    if !from_end {
        ordered.reverse();
    }
    for slice in ordered {
        if stopped {
            // Past the straddling slice on the kept side: keep whole.
            if from_end {
                kept_slices.push((*slice).clone());
            } else {
                kept_slices.insert(0, (*slice).clone());
            }
            continue;
        }
        let slice_advance = slice.total_advance();
        if kept_advance + slice_advance <= keep_target {
            kept_advance += slice_advance;
            if from_end {
                kept_slices.push((*slice).clone());
            } else {
                kept_slices.insert(0, (*slice).clone());
            }
            continue;
        }
        // Straddling slice: keep a cluster-clean prefix/suffix of it.
        // `keep_*` counts from the cut side; translate to a leading split
        // point (trailing keeps start at `total - keep`).
        let total = slice.glyph_count();
        let keep_count = if from_end {
            keep_leading_glyphs_for_advance(slice, sat_sub(keep_target, kept_advance))
        } else {
            keep_trailing_glyphs_for_advance(slice, sat_sub(keep_target, kept_advance))
        };
        let split_at = if from_end {
            keep_count.min(total)
        } else {
            total.saturating_sub(keep_count)
        };
        let (leading, trailing) = slice.split_at_glyph(split_at);
        let kept_part = if from_end { leading } else { trailing };
        kept_advance += kept_part.total_advance();
        if from_end {
            kept_slices.push(kept_part);
        } else {
            kept_slices.insert(0, kept_part);
        }
        stopped = true;
    }
    (kept_slices, sat_sub(original_advance, kept_advance))
}

/// Truncate a finished line's fragments for `text-overflow: ellipsis`
/// (phase 1). `fragments` are in visual order; the line overflows when
/// its content exceeds `available_inline_size`. Content is truncated from
/// the logical-end side (visual end for LTR blocks, visual start for RTL)
/// to make room for the ellipsis, which is appended as a new trailing
/// [`Fragment::Text`] reusing the truncated run's base and style data
/// with a zero-width DOM range at the truncation boundary — selection
/// stringification still yields the full text. Does nothing unless the
/// gate holds and the line actually overflows.
pub(super) fn truncate_line_for_ellipsis(
    layout_context: &LayoutContext,
    block_style: &ComputedValues,
    fragments: &mut Vec<Fragment>,
    available_inline_size: Au,
) {
    if !ellipsis_end_style(block_style) {
        return;
    }
    let content = content_inline_size(fragments);
    if content <= available_inline_size {
        return;
    }
    // Block direction decides the truncation side in visual order: the
    // logical end is the visual end for LTR, the visual start for RTL.
    let from_end = block_style.writing_mode.is_bidi_ltr();

    let Some((ellipsis_font, ellipsis_slices, ellipsis_advance)) =
        shape_ellipsis(block_style, &layout_context.font_context)
    else {
        return;
    };
    // Not even the first character plus the ellipsis fits: clip without a
    // marker (spec: the first character must be clipped, not ellipsed).
    if ellipsis_advance >= available_inline_size {
        return;
    }
    let mut excess = content + ellipsis_advance - available_inline_size;

    // Walk fragments from the truncation side, dropping whole fragments
    // (atomics go whole — they cannot be partially shown) and shortening
    // the first text fragment that straddles the cut point.
    let mut scan = if from_end { fragments.len() } else { 0 };
    loop {
        let candidate = if from_end {
            if scan == 0 {
                break;
            }
            scan -= 1;
            scan
        } else {
            if scan >= fragments.len() {
                break;
            }
            let current = scan;
            scan += 1;
            current
        };
        let fragment_advance = match &fragments[candidate] {
            Fragment::Text(text) => text
                .glyphs
                .iter()
                .map(|slice| slice.total_advance())
                .sum(),
            Fragment::Box(box_fragment) => box_fragment.base.rect().size.width,
            _ => continue,
        };
        if fragment_advance <= excess {
            excess -= fragment_advance;
            fragments.remove(candidate);
            if from_end {
                scan = fragments.len().min(scan);
            } else {
                scan = scan.saturating_sub(1);
            }
            if excess.is_zero() {
                break;
            }
            continue;
        }
        if !matches!(&fragments[candidate], Fragment::Text(_)) {
            // Atomic box straddling the cut: drop it whole and continue
            // freeing space past it.
            excess = sat_sub(excess, fragment_advance);
            fragments.remove(candidate);
            if from_end {
                scan = fragments.len().min(scan);
            } else {
                scan = scan.saturating_sub(1);
            }
            continue;
        }
        let Fragment::Text(text) = &fragments[candidate] else {
            unreachable!("non-text fragments handled above");
        };
        let (kept_slices, freed) = truncate_text_glyphs(text, excess, from_end);
        if kept_slices.is_empty() {
            // Fully drained: drop the fragment and keep the boundary at
            // the neighboring kept text.
            excess = sat_sub(excess, freed);
            fragments.remove(candidate);
            if from_end {
                scan = fragments.len().min(scan);
            } else {
                scan = scan.saturating_sub(1);
            }
            continue;
        }
        // Build the shortened replacement fragment in place: shrunk box
        // plus a DOM range covering only the surviving characters.
        let kept_advance: Au = kept_slices
            .iter()
            .map(|slice| slice.total_advance())
            .sum();
        let kept_chars: u32 = kept_slices
            .iter()
            .map(|slice| slice.character_count().0)
            .sum();
        let mut rect = text.base.rect();
        if from_end {
            rect.size.width = kept_advance;
        } else {
            rect.origin.x += sat_sub(rect.size.width, kept_advance);
            rect.size.width = kept_advance;
        }
        let range = text.character_range_in_dom_node.clone();
        let range_len = range.end.0.saturating_sub(range.start.0);
        let kept_chars = kept_chars.min(range_len);
        let new_range = if from_end {
            range.start..(range.start + Utf32CodeUnits(kept_chars))
        } else {
            (range.end - Utf32CodeUnits(kept_chars))..range.end
        };
        let Fragment::Text(old) = &fragments[candidate] else {
            unreachable!("non-text fragments handled above");
        };
        fragments[candidate] = Fragment::Text(Arc::new(TextFragment {
            base: BaseFragment::new(
                BaseFragmentInfo {
                    tag: old.base.tag,
                    flags: old.base.flags,
                },
                rect,
            ),
            run_data: old.run_data.clone(),
            font_metrics: old.font_metrics.clone(),
            font_key: old.font_key,
            glyphs: kept_slices,
            justification_adjustment: old.justification_adjustment,
            character_range_in_dom_node: new_range,
            is_empty_for_text_cursor: old.is_empty_for_text_cursor,
        }));
        excess = sat_sub(excess, freed);
        break;
    }

    // Truncation-side-most kept fragment anchors the ellipsis edge. If no
    // text run survived, there is nothing sensible to attach the marker
    // to: clip without it.
    let edge_index = if from_end {
        fragments.iter().rposition(|fragment| {
            matches!(fragment, Fragment::Text(_) | Fragment::Box(_))
        })
    } else {
        fragments.iter().position(|fragment| {
            matches!(fragment, Fragment::Text(_) | Fragment::Box(_))
        })
    };
    let Some(edge_index) = edge_index else {
        return;
    };
    let boundary_text = if from_end {
        fragments.iter().rev().find_map(|fragment| match fragment {
            Fragment::Text(text) => Some(text),
            _ => None,
        })
    } else {
        fragments.iter().find_map(|fragment| match fragment {
            Fragment::Text(text) => Some(text),
            _ => None,
        })
    };
    let Some(boundary_text) = boundary_text else {
        return;
    };
    let boundary = if from_end {
        boundary_text.character_range_in_dom_node.end
    } else {
        boundary_text.character_range_in_dom_node.start
    };
    let edge_rect = match &fragments[edge_index] {
        Fragment::Text(text) => text.base.rect(),
        Fragment::Box(box_fragment) => box_fragment.base.rect(),
        _ => unreachable!("edge index always points at text or a box"),
    };
    let mut ellipsis_rect = edge_rect;
    if from_end {
        ellipsis_rect.origin.x += ellipsis_rect.size.width;
    } else {
        ellipsis_rect.origin.x = sat_sub(ellipsis_rect.origin.x, ellipsis_advance);
    }
    ellipsis_rect.size.width = ellipsis_advance;
    let base = BaseFragment::new(
        BaseFragmentInfo {
            tag: boundary_text.base.tag,
            flags: boundary_text.base.flags,
        },
        ellipsis_rect,
    );
    let ellipsis_fragment = Fragment::Text(Arc::new(TextFragment {
        base,
        run_data: boundary_text.run_data.clone(),
        font_metrics: ellipsis_font.metrics.clone(),
        font_key: ellipsis_font.key(
            layout_context.painter_id,
            &layout_context.font_context,
        ),
        glyphs: ellipsis_slices,
        justification_adjustment: Au::zero(),
        character_range_in_dom_node: boundary..boundary,
        is_empty_for_text_cursor: false,
    }));
    if from_end {
        fragments.push(ellipsis_fragment);
    } else {
        fragments.insert(0, ellipsis_fragment);
    }
}
