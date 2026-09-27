"""Unit tests for rs.pixeldiff: pure-Python RGB diff, crop/pad, masks."""

import unittest

from rs import pixeldiff


def solid(w, h, rgb):
    return bytes(rgb) * (w * h)


class DiffPercentTest(unittest.TestCase):
    def test_identical_is_zero(self):
        a = solid(4, 4, (10, 20, 30))
        self.assertEqual(pixeldiff.diff_percent(a, a, 4, 4), 0.0)

    def test_fully_different_is_hundred(self):
        a = solid(4, 4, (0, 0, 0))
        b = solid(4, 4, (255, 255, 255))
        self.assertEqual(pixeldiff.diff_percent(a, b, 4, 4), 100.0)

    def test_quarter_different(self):
        w, h = 4, 4
        a = bytearray(solid(w, h, (0, 0, 0)))
        b = bytearray(a)
        for i in range(4):  # first row of four pixels -> 4/16 = 25 %
            b[i * 3 : i * 3 + 3] = bytes((200, 0, 0))
        self.assertEqual(pixeldiff.diff_percent(bytes(a), bytes(b), w, h), 25.0)

    def test_small_deltas_under_threshold_are_equal(self):
        a = solid(2, 2, (100, 100, 100))
        b = solid(2, 2, (110, 95, 100))  # anti-aliasing noise
        self.assertEqual(pixeldiff.diff_percent(a, b, 2, 2, threshold=32), 0.0)
        self.assertEqual(pixeldiff.diff_percent(a, b, 2, 2, threshold=5), 100.0)

    def test_size_mismatch_raises(self):
        with self.assertRaises(ValueError):
            pixeldiff.diff_percent(solid(2, 2, (0, 0, 0)), solid(3, 3, (0, 0, 0)), 2, 2)

    def test_rounding_two_places(self):
        w, h = 3, 1
        a = solid(w, h, (0, 0, 0))
        b = bytes((255, 0, 0)) + solid(2, 1, (0, 0, 0))
        self.assertEqual(pixeldiff.diff_percent(a, b, w, h), 33.33)


class MaskTest(unittest.TestCase):
    def test_mask_marks_differing_pixels(self):
        a = solid(2, 1, (0, 0, 0))
        b = bytes((0, 0, 0, 255, 255, 255))
        self.assertEqual(pixeldiff.diff_mask(a, b, 2, 1), bytes((0, 255)))


class FitTest(unittest.TestCase):
    def test_crop_larger_image(self):
        # 3x2 image, rows [r g b] [w k w]; crop to 2x1 keeps the top-left.
        img = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 255, 255))
        self.assertEqual(pixeldiff.fit(img, 3, 2, 2, 1), bytes((255, 0, 0, 0, 255, 0)))

    def test_pad_smaller_image_with_fill(self):
        img = bytes((1, 2, 3))
        out = pixeldiff.fit(img, 1, 1, 2, 2, fill=(9, 9, 9))
        self.assertEqual(out, bytes((1, 2, 3, 9, 9, 9, 9, 9, 9, 9, 9, 9)))

    def test_same_size_is_identity(self):
        img = solid(2, 2, (5, 6, 7))
        self.assertEqual(pixeldiff.fit(img, 2, 2, 2, 2), img)

    def test_padding_counts_as_different(self):
        # A blank page that is shorter than the viewport must not score as a match.
        small = solid(2, 1, (255, 255, 255))
        full = solid(2, 2, (255, 255, 255))
        padded = pixeldiff.fit(small, 2, 1, 2, 2)
        self.assertEqual(pixeldiff.diff_percent(padded, full, 2, 2), 50.0)


if __name__ == "__main__":
    unittest.main()
