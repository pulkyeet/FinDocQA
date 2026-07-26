"""Tests for delta/narrate.py — evidence pooling, citation resolution, parsing.

The load-bearing guarantee here is that a citation in the finished prose can
only point at a real, quote-validated change record. These tests exercise that
boundary directly; the LLM call itself is not exercised.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.narrate import (
    build_evidence_pool,
    format_evidence_block,
    format_xbrl_block,
    parse_narrative_response,
    resolve_citations,
    _drop_dangling_sentence,
    _interleave_pull_quotes,
)


def _interp(cid, materiality="material", anchor_year=("FY2024", "FY2025"), **kw):
    base = {
        "change_id": cid,
        "change_type": "expanded",
        "materiality": materiality,
        "summary": f"summary for {cid}",
        "why_it_matters": "because",
        "old_quote": "was text",
        "new_quote": "now text",
        "_y_old": anchor_year[0],
        "_y_new": anchor_year[1],
    }
    base.update(kw)
    return base


class TestBuildEvidencePool(unittest.TestCase):
    def test_collects_across_anchors(self):
        interps = {
            "item1a_risk": [_interp("c1")],
            "item7a_market_risk": [_interp("c2", "notable")],
            "item1_business": [_interp("c3")],
        }
        pool = build_evidence_pool(interps, ["item1a_risk", "item7a_market_risk"])
        ids = [e["change_id"] for e in pool]
        self.assertEqual(sorted(ids), ["c1", "c2"])

    def test_labels_are_sequential(self):
        interps = {"item1a_risk": [_interp(f"c{i}") for i in range(3)]}
        pool = build_evidence_pool(interps, ["item1a_risk"])
        self.assertEqual([e["label"] for e in pool], ["E1", "E2", "E3"])

    def test_boilerplate_excluded(self):
        interps = {"item1a_risk": [_interp("c1", "boilerplate"), _interp("c2")]}
        pool = build_evidence_pool(interps, ["item1a_risk"])
        self.assertEqual([e["change_id"] for e in pool], ["c2"])

    def test_unvalidated_excluded(self):
        """An unvalidated record has no trustworthy quote, so it cannot be cited."""
        interps = {"item1a_risk": [_interp("c1", _unvalidated=True), _interp("c2")]}
        pool = build_evidence_pool(interps, ["item1a_risk"])
        self.assertEqual([e["change_id"] for e in pool], ["c2"])

    def test_material_ranked_before_notable(self):
        interps = {"item1a_risk": [
            _interp("notable1", "notable", ("FY2021", "FY2022")),
            _interp("material1", "material", ("FY2024", "FY2025")),
        ]}
        pool = build_evidence_pool(interps, ["item1a_risk"])
        self.assertEqual(pool[0]["change_id"], "material1")

    def test_cap_keeps_material(self):
        interps = {"item1a_risk":
                   [_interp(f"n{i}", "notable") for i in range(10)]
                   + [_interp("m1", "material")]}
        pool = build_evidence_pool(interps, ["item1a_risk"], max_items=3)
        self.assertEqual(len(pool), 3)
        self.assertIn("m1", [e["change_id"] for e in pool])

    def test_missing_anchor_is_empty(self):
        self.assertEqual(build_evidence_pool({}, ["item1a_risk"]), [])

    def test_section_name_resolved(self):
        pool = build_evidence_pool({"item1a_risk": [_interp("c1")]}, ["item1a_risk"])
        self.assertEqual(pool[0]["section_name"], "Risk Factors (1A)")


class TestResolveCitations(unittest.TestCase):
    def _pool(self):
        return [
            {"label": "E1", "change_id": "cid-1", "section_name": "Risk Factors (1A)",
             "y_old": "FY2023", "y_new": "FY2024", "summary": "s1",
             "old_quote": "a", "new_quote": "b"},
            {"label": "E2", "change_id": "cid-2", "section_name": "MD&A (7)",
             "y_old": "FY2024", "y_new": "FY2025", "summary": "s2",
             "old_quote": "c", "new_quote": "d"},
        ]

    def test_marker_becomes_superscript_link(self):
        paras, notes = resolve_citations("Risk rose. [E1]", self._pool())
        self.assertIn('<sup class="cite">', paras[0])
        self.assertIn('href="#ev-cid-1"', paras[0])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["n"], 1)

    def test_unknown_label_dropped(self):
        """A hallucinated citation must vanish, not render a dead link."""
        paras, notes = resolve_citations("Claim. [E99] Another. [E1]", self._pool())
        self.assertNotIn("E99", paras[0])
        self.assertNotIn("ev-E99", paras[0])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["change_id"], "cid-1")

    def test_numbering_follows_first_appearance(self):
        paras, notes = resolve_citations("First. [E2] Second. [E1]", self._pool())
        self.assertEqual([n["change_id"] for n in notes], ["cid-2", "cid-1"])
        self.assertEqual([n["n"] for n in notes], [1, 2])

    def test_repeat_citation_reuses_number(self):
        paras, notes = resolve_citations("A. [E1] B. [E1]", self._pool())
        self.assertEqual(len(notes), 1)
        self.assertEqual(paras[0].count('href="#ev-cid-1"'), 2)

    def test_paragraphs_split_on_blank_line(self):
        paras, _ = resolve_citations("One.\n\nTwo.\n\nThree.", self._pool())
        self.assertEqual(len(paras), 3)

    def test_html_escaped(self):
        """Model-emitted markup must not become live HTML in the report."""
        paras, _ = resolve_citations('<script>alert(1)</script> [E1]', self._pool())
        self.assertNotIn("<script>", paras[0])
        self.assertIn("&lt;script&gt;", paras[0])
        # Escaping must not break the citation that follows it.
        self.assertIn('<sup class="cite">', paras[0])

    def test_no_citations_still_renders(self):
        paras, notes = resolve_citations("Plain prose.", self._pool())
        self.assertEqual(paras, ["Plain prose."])
        self.assertEqual(notes, [])


class TestParseNarrativeResponse(unittest.TestCase):
    def test_full_format(self):
        raw = "NARRATIVE:\nApple did a thing. [E1]\n\nPULL_QUOTES: E3, E12"
        text, quotes = parse_narrative_response(raw)
        self.assertEqual(text, "Apple did a thing. [E1]")
        self.assertEqual(quotes, ["E3", "E12"])

    def test_missing_pull_quotes(self):
        text, quotes = parse_narrative_response("NARRATIVE:\nProse here.")
        self.assertEqual(text, "Prose here.")
        self.assertEqual(quotes, [])

    def test_missing_narrative_header(self):
        """A model that ignores the format still hands back usable prose."""
        text, quotes = parse_narrative_response("Just the prose, no header.")
        self.assertEqual(text, "Just the prose, no header.")

    def test_evidence_echo_stripped(self):
        raw = "NARRATIVE:\nProse.\n\nEVIDENCE:\n[E1] blah blah"
        text, _ = parse_narrative_response(raw)
        self.assertEqual(text, "Prose.")

    def test_error_response(self):
        self.assertEqual(parse_narrative_response("[TIMEOUT]"), ("", []))
        self.assertEqual(parse_narrative_response("[ERROR: boom]"), ("", []))
        self.assertEqual(parse_narrative_response(""), ("", []))

    def test_truncated_response_loses_fragment(self):
        raw = "NARRATIVE:\nComplete sentence. Another one. But the\n[TRUNCATED]"
        text, _ = parse_narrative_response(raw)
        self.assertEqual(text, "Complete sentence. Another one.")


class TestDropDanglingSentence(unittest.TestCase):
    def test_untruncated_untouched(self):
        s = "A sentence that trails off"
        self.assertEqual(_drop_dangling_sentence(s), s)

    def test_fragment_removed(self):
        s = "First. Second. Capital allocation showed tension. The[TRUNCATED]"
        self.assertEqual(_drop_dangling_sentence(s),
                         "First. Second. Capital allocation showed tension.")

    def test_handles_quoted_sentence_end(self):
        s = 'He said "no." And then the[TRUNCATED]'
        self.assertEqual(_drop_dangling_sentence(s), 'He said "no."')

    def test_no_complete_sentence(self):
        s = "just a fragment[TRUNCATED]"
        self.assertEqual(_drop_dangling_sentence(s), "just a fragment")


class TestFormatBlocks(unittest.TestCase):
    def test_evidence_block_has_labels_and_quotes(self):
        pool = build_evidence_pool({"item1a_risk": [_interp("c1")]}, ["item1a_risk"])
        block = format_evidence_block(pool)
        self.assertIn("[E1]", block)
        self.assertIn("Risk Factors (1A)", block)
        self.assertIn("FY2024 -> FY2025", block)
        self.assertIn('was: "was text"', block)
        self.assertIn('now: "now text"', block)

    def test_xbrl_block(self):
        series = {"NetIncomeLoss": {
            "FY2024": {"value": 96995000000, "pct": None},
            "FY2025": {"value": 93736000000, "pct": -3.36},
        }}
        block = format_xbrl_block(
            series, ["NetIncomeLoss"], {"NetIncomeLoss": "Net Income"},
            ["FY2024", "FY2025"], lambda v, t: f"${v/1e9:.1f}B",
        )
        self.assertIn("Net Income", block)
        self.assertIn("FY2024 $97.0B", block)
        self.assertIn("(-3.4%)", block)

    def test_xbrl_block_empty(self):
        self.assertEqual(format_xbrl_block({}, ["X"], {}, ["FY2025"], str), "")


class TestInterleavePullQuotes(unittest.TestCase):
    def test_quotes_inserted_between_paragraphs(self):
        paras = [f"p{i}" for i in range(6)]
        quotes = [{"new_quote": "q1"}]
        blocks = _interleave_pull_quotes(paras, quotes)
        self.assertEqual(sum(1 for b in blocks if b["type"] == "pullquote"), 1)
        self.assertEqual(sum(1 for b in blocks if b["type"] == "p"), 6)

    def test_never_trailing(self):
        paras = [f"p{i}" for i in range(6)]
        blocks = _interleave_pull_quotes(paras, [{"new_quote": "q"}])
        self.assertEqual(blocks[-1]["type"], "p")

    def test_short_chapter_skips_quotes(self):
        blocks = _interleave_pull_quotes(["p0", "p1"], [{"new_quote": "q"}])
        self.assertTrue(all(b["type"] == "p" for b in blocks))

    def test_no_quotes(self):
        blocks = _interleave_pull_quotes(["p0", "p1", "p2"], [])
        self.assertEqual(len(blocks), 3)


if __name__ == "__main__":
    unittest.main()
