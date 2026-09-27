"""Pixel diff over raw RGB bytes (pure Python), plus Pillow helpers for PNG files.

The pure functions work on packed 8-bit RGB rows (3 bytes per pixel, row
major) so they can be unit tested without Pillow. A pixel counts as
different when any channel differs by more than `threshold`, which absorbs
anti-aliasing and color-management noise between engines.
"""

from typing import Tuple

DEFAULT_THRESHOLD = 32
# Padding for a screenshot smaller than the viewport: a color no page is
# likely to paint, so missing area always counts as different.
PAD_FILL = (255, 0, 255)


def _check(a: bytes, b: bytes, width: int, height: int) -> None:
    expected = width * height * 3
    if len(a) != expected or len(b) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height} RGB, got {len(a)} and {len(b)}")


def diff_mask(a: bytes, b: bytes, width: int, height: int, threshold: int = DEFAULT_THRESHOLD) -> bytes:
    """One byte per pixel: 255 where the images differ, 0 where they match."""
    _check(a, b, width, height)
    out = bytearray(width * height)
    for p in range(width * height):
        i = p * 3
        if (
            abs(a[i] - b[i]) > threshold
            or abs(a[i + 1] - b[i + 1]) > threshold
            or abs(a[i + 2] - b[i + 2]) > threshold
        ):
            out[p] = 255
    return bytes(out)


def diff_percent(a: bytes, b: bytes, width: int, height: int, threshold: int = DEFAULT_THRESHOLD) -> float:
    """Percentage of differing pixels, rounded to two decimal places."""
    if a == b:
        _check(a, b, width, height)
        return 0.0
    mask = diff_mask(a, b, width, height, threshold)
    differing = len(mask) - mask.count(0)
    return round(100.0 * differing / (width * height), 2)


def fit(
    rgb: bytes, width: int, height: int, target_w: int, target_h: int, fill: Tuple[int, int, int] = PAD_FILL
) -> bytes:
    """Crop or pad an RGB image to target size, anchored at the top-left."""
    if len(rgb) != width * height * 3:
        raise ValueError(f"expected {width * height * 3} bytes for {width}x{height} RGB, got {len(rgb)}")
    if (width, height) == (target_w, target_h):
        return rgb
    fill_px = bytes(fill)
    out = bytearray()
    copy_w = min(width, target_w)
    for y in range(target_h):
        if y < height:
            start = y * width * 3
            out += rgb[start : start + copy_w * 3]
            out += fill_px * (target_w - copy_w)
        else:
            out += fill_px * target_w
    return bytes(out)


# --- Pillow helpers (used by the report, not by the unit tests above) ---


def load_rgb(path: str, target_w: int, target_h: int) -> bytes:
    from PIL import Image  # imported lazily: only the report needs Pillow

    with Image.open(path) as im:
        im = im.convert("RGB")
        return fit(im.tobytes(), im.width, im.height, target_w, target_h)


def write_thumbs(
    servo_png: str,
    chrome_png: str,
    out_prefix: str,
    width: int,
    height: int,
    threshold: int = DEFAULT_THRESHOLD,
    thumb_w: int = 320,
) -> dict:
    """Write servo/chrome/diff JPEG thumbnails; returns their file names."""
    from PIL import Image

    a = load_rgb(servo_png, width, height)
    b = load_rgb(chrome_png, width, height)
    mask = diff_mask(a, b, width, height, threshold)
    thumb_h = round(height * thumb_w / width)
    names = {}
    base = Image.frombytes("RGB", (width, height), b).convert("L").convert("RGB")
    red = Image.new("RGB", (width, height), (230, 0, 60))
    overlay = Image.composite(red, base, Image.frombytes("L", (width, height), mask))
    for key, img in (
        ("servo", Image.frombytes("RGB", (width, height), a)),
        ("chrome", Image.frombytes("RGB", (width, height), b)),
        ("diff", overlay),
    ):
        name = f"{out_prefix}.{key}.jpg"
        img.resize((thumb_w, thumb_h), Image.LANCZOS).save(name, "JPEG", quality=72)
        names[key] = name
    return names
