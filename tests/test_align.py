"""Tests for delta/align.py — section and paragraph alignment."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.align import (
    split_into_paragraphs,
    group_by_anchor,
    align_sections,
    match_paragraphs,
)


class TestSplitParagraphs(unittest.TestCase):
    def test_multi_paragraph(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = split_into_paragraphs(text)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "First paragraph.")
        self.assertEqual(result[1], "Second paragraph.")
        self.assertEqual(result[2], "Third paragraph.")

    def test_empty_input(self):
        self.assertEqual(split_into_paragraphs(""), [])

    def test_whitespace_only(self):
        self.assertEqual(split_into_paragraphs("\n\n   \n\n"), [])

    def test_single_paragraph(self):
        text = "Just one paragraph."
        result = split_into_paragraphs(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Just one paragraph.")

    def test_extra_newlines(self):
        text = "A.\n\n\n\nB."
        result = split_into_paragraphs(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "A.")
        self.assertEqual(result[1], "B.")

    def test_leading_trailing_whitespace(self):
        text = "  \n\nHello.\n\n  "
        result = split_into_paragraphs(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Hello.")


class TestGroupByAnchor(unittest.TestCase):
    def test_basic_grouping(self):
        chunks = [
            {"chunk_id": "1", "anchor": "item1a_risk", "text": "a"},
            {"chunk_id": "2", "anchor": "item1a_risk", "text": "b"},
            {"chunk_id": "3", "anchor": "item7_mdna", "text": "c"},
            {"chunk_id": "4", "anchor": None, "text": "d"},
        ]
        result = group_by_anchor(chunks)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result["item1a_risk"]), 2)
        self.assertEqual(len(result["item7_mdna"]), 1)
        self.assertEqual(len(result["unknown"]), 1)

    def test_empty_input(self):
        self.assertEqual(group_by_anchor([]), {})


class TestAlignSections(unittest.TestCase):
    def test_matching_pairs(self):
        old_c = [
            {"chunk_id": "old1", "anchor": "item1a_risk", "text": "old risk"},
            {"chunk_id": "old2", "anchor": "item7_mdna", "text": "old mdna"},
        ]
        new_c = [
            {"chunk_id": "new1", "anchor": "item1a_risk", "text": "new risk"},
            {"chunk_id": "new2", "anchor": "item7_mdna", "text": "new mdna"},
        ]
        pairs = align_sections(old_c, new_c)
        self.assertEqual(len(pairs), 2)
        for anchor, oc, nc in pairs:
            self.assertGreater(len(oc), 0)
            self.assertGreater(len(nc), 0)

    def test_structural_addition(self):
        old_c = [{"chunk_id": "old1", "anchor": "item1a_risk", "text": "old"}]
        new_c = [
            {"chunk_id": "new1", "anchor": "item1a_risk", "text": "new"},
            {"chunk_id": "new2", "anchor": "item1c_cybersecurity", "text": "cyber"},
        ]
        pairs = align_sections(old_c, new_c)
        self.assertEqual(len(pairs), 2)
        anchors_found = {a for a, _, _ in pairs}
        self.assertIn("item1a_risk", anchors_found)
        self.assertIn("item1c_cybersecurity", anchors_found)

        for a, oc, nc in pairs:
            if a == "item1c_cybersecurity":
                self.assertEqual(len(oc), 0)
                self.assertEqual(len(nc), 1)

    def test_structural_removal(self):
        old_c = [
            {"chunk_id": "old1", "anchor": "item1a_risk", "text": "old"},
            {"chunk_id": "old2", "anchor": "item9c_foreign", "text": "foreign"},
        ]
        new_c = [{"chunk_id": "new1", "anchor": "item1a_risk", "text": "new"}]
        pairs = align_sections(old_c, new_c)
        self.assertEqual(len(pairs), 2)
        for a, oc, nc in pairs:
            if a == "item9c_foreign":
                self.assertEqual(len(oc), 1)
                self.assertEqual(len(nc), 0)

    def test_empty_inputs(self):
        self.assertEqual(align_sections([], []), [])


class TestMatchParagraphs(unittest.TestCase):
    def test_empty_both(self):
        import numpy as np
        result = match_paragraphs([], [], np.array([]).reshape(0, 0), np.array([]).reshape(0, 0))
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_all_removed(self):
        import numpy as np
        old_paras = ["para one", "para two"]
        new_paras = []
        old_embs = np.array([[1.0], [1.0]])
        new_embs = np.array([]).reshape(0, 0)
        result = match_paragraphs(old_paras, new_paras, old_embs, new_embs)
        self.assertEqual(len(result["removed"]), 2)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["added"], [])

    def test_all_added(self):
        import numpy as np
        old_paras = []
        new_paras = ["para one"]
        old_embs = np.array([]).reshape(0, 0)
        new_embs = np.array([[1.0]])
        result = match_paragraphs(old_paras, new_paras, old_embs, new_embs)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["removed"], [])

    def test_floor_cutoff(self):
        import numpy as np
        old_paras = ["cat"]
        new_paras = ["dog"]
        old_embs = np.array([[1.0, 0.0]])
        new_embs = np.array([[0.0, 1.0]])
        result = match_paragraphs(old_paras, new_paras, old_embs, new_embs, similarity_floor=0.9)
        self.assertEqual(len(result["matches"]), 0)
        self.assertEqual(result["added"], [0])
        self.assertEqual(result["removed"], [0])

    def test_greedy_match(self):
        import numpy as np
        old_paras = ["a b c", "d e f"]
        new_paras = ["a b c", "x y z"]
        old_embs = np.array([[1.0, 0.0], [0.0, 1.0]])
        new_embs = np.array([[1.0, 0.0], [0.0, 0.0]])
        result = match_paragraphs(old_paras, new_paras, old_embs, new_embs, similarity_floor=0.0)
        self.assertEqual(len(result["matches"]), 2)
        first = result["matches"][0]
        self.assertEqual(first["old_idx"], 0)
        self.assertEqual(first["new_idx"], 0)


class TestMultiYearAlignment(unittest.TestCase):
    def test_align_two_years_of_aapl(self):
        from delta.align import load_chunks_for_year, align_sections
        old_chunks = load_chunks_for_year("AAPL", "FY2024")
        new_chunks = load_chunks_for_year("AAPL", "FY2025")
        pairs = align_sections(old_chunks, new_chunks)
        # Expect at least item1a_risk, item7_mdna, item8_financials
        anchors = {a for a, _, _ in pairs}
        self.assertIn("item1a_risk", anchors)
        self.assertIn("item7_mdna", anchors)
        self.assertIn("item8_financials", anchors)
        # All pairs should have content in at least one year
        for anchor, oc, nc in pairs:
            self.assertTrue(len(oc) > 0 or len(nc) > 0,
                            f"Section {anchor} has no chunks in either year")


if __name__ == "__main__":
    unittest.main()
