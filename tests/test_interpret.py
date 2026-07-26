"""Tests for delta/interpret.py — prompt-text truncation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.interpret import _truncate_at_word_boundary


class TestTruncateAtWordBoundary(unittest.TestCase):
    def test_short_text_untouched(self):
        text = "A short sentence."
        self.assertEqual(_truncate_at_word_boundary(text, limit=500), text)

    def test_never_cuts_mid_word(self):
        text = "confirmed the Commission's decision on state aid " * 20
        out = _truncate_at_word_boundary(text, limit=50)
        self.assertLessEqual(len(out), 50)
        # The source character right after the cut must be a space (or the
        # cut coincided with the end of the string) — never mid-word.
        self.assertTrue(len(out) == len(text) or text[len(out)] == " ")

    def test_exact_boundary_example(self):
        text = "On September 10, 2024, the ECJ announced that it had set aside the 2020 judgment of the General Court and confirmed the Commission's decision."
        out = _truncate_at_word_boundary(text, limit=120)
        self.assertLessEqual(len(out), 120)
        self.assertFalse(out.endswith("Comm"))
        self.assertTrue(text.startswith(out))

    def test_no_whitespace_falls_back_to_hard_cut(self):
        text = "a" * 600
        out = _truncate_at_word_boundary(text, limit=500)
        self.assertEqual(len(out), 500)

    def test_default_limit(self):
        text = "word " * 200
        out = _truncate_at_word_boundary(text)
        self.assertLessEqual(len(out), 500)
        self.assertTrue(out.endswith("word") or out == "")


if __name__ == "__main__":
    unittest.main()
