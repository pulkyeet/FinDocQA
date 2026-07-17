"""Tests for delta/diff.py — classification, word deltas, churn."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.diff import classify_pair, word_delta, compute_churn_score, make_diff_record


class TestClassifyPair(unittest.TestCase):
    # Thresholds tuned on data/eval/diff_labels.jsonl (47-pair labeled sample)
    def test_unchanged_boundary(self):
        self.assertEqual(classify_pair(0.95), "unchanged")
        self.assertEqual(classify_pair(1.0), "unchanged")

    def test_minor_boundary(self):
        self.assertEqual(classify_pair(0.94), "modified_minor")
        self.assertEqual(classify_pair(0.81), "modified_minor")

    def test_major_boundary(self):
        self.assertEqual(classify_pair(0.79), "modified_major")
        self.assertEqual(classify_pair(0.60), "modified_major")

    def test_below_major(self):
        self.assertEqual(classify_pair(0.59), "modified_minor")


class TestWordDelta(unittest.TestCase):
    def test_additions_only(self):
        result = word_delta("hello world", "hello new world")
        self.assertIn("new", result["added"])
        self.assertEqual(result["removed"], [])

    def test_removals_only(self):
        result = word_delta("hello old world", "hello world")
        self.assertIn("old", result["removed"])
        self.assertEqual(result["added"], [])

    def test_both(self):
        result = word_delta("apple banana cherry", "apple grape cherry")
        self.assertIn("grape", result["added"])
        self.assertIn("banana", result["removed"])

    def test_no_change(self):
        result = word_delta("same text", "same text")
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_punctuation(self):
        result = word_delta("Hello, world!", "Hello world!")
        self.assertIn(",", result["removed"])


class TestComputeChurn(unittest.TestCase):
    def test_all_unchanged(self):
        paras = [{"old_text": "hello world", "new_text": "hello world"}]
        classifications = ["unchanged"]
        self.assertEqual(compute_churn_score(paras, classifications), 0.0)

    def test_all_changed(self):
        paras = [{"old_text": "hello", "new_text": "goodbye"}]
        classifications = ["modified_major"]
        self.assertEqual(compute_churn_score(paras, classifications), 1.0)

    def test_mixed(self):
        paras = [
            {"old_text": "aaaa", "new_text": "aaaa"},
            {"old_text": "bbbb", "new_text": "cccc"},
        ]
        classifications = ["unchanged", "modified_major"]
        self.assertEqual(compute_churn_score(paras, classifications), 0.5)

    def test_empty(self):
        self.assertEqual(compute_churn_score([], []), 0.0)


class TestMakeDiffRecord(unittest.TestCase):
    def test_record_shape(self):
        rec = make_diff_record(
            "AAPL", "item1a_risk", ("FY2024", "FY2025"),
            "modified_major", 0.71, 34, 35,
            "old text here", "new text here",
        )
        self.assertEqual(rec["ticker"], "AAPL")
        self.assertEqual(rec["anchor"], "item1a_risk")
        self.assertEqual(rec["year_pair"], ["FY2024", "FY2025"])
        self.assertEqual(rec["classification"], "modified_major")
        self.assertEqual(rec["similarity"], 0.71)
        self.assertEqual(rec["old_para_idx"], 34)
        self.assertEqual(rec["new_para_idx"], 35)
        self.assertEqual(rec["old_text"], "old text here")
        self.assertEqual(rec["new_text"], "new text here")
        self.assertIn("word_delta", rec)
        self.assertIn("change_id", rec)


if __name__ == "__main__":
    unittest.main()
