import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scoring import (
    extract_numbers,
    numeric_match,
    retrieval_score,
    routing_score,
)


class TestExtractNumbers(unittest.TestCase):
    def test_bare_integer(self):
        self.assertEqual(extract_numbers("The value is 42."), [42])

    def test_negative_from_parens(self):
        self.assertEqual(extract_numbers("loss of (5) million"), [-5e6])

    def test_negative_from_leading_minus(self):
        self.assertEqual(extract_numbers("decline of -3.2 billion"), [-3.2e9])

    def test_inline_word_scale(self):
        self.assertEqual(extract_numbers("revenue of 1.5 billion"), [1.5e9])

    def test_inline_abbr_scale(self):
        self.assertEqual(extract_numbers("$500M"), [500e6])

    def test_percentage_emits_raw_and_decimal(self):
        nums = extract_numbers("margin of 9.2%")
        self.assertIn(9.2, nums)
        self.assertIn(0.092, nums)

    def test_year_skip(self):
        nums = extract_numbers("In 2025 we had revenue.")
        self.assertNotIn(2025, nums)

    def test_chunk_id_skip(self):
        nums = extract_numbers("See chunk 12345 for details.")
        self.assertNotIn(12345, nums)

    def test_citation_block_strip(self):
        nums = extract_numbers("Answer: $10M. Citations: [chunk_abc, chunk_def]")
        self.assertEqual(nums, [10e6])

    def test_citation_line_strip(self):
        nums = extract_numbers("Answer: 99 billion. citations: chunk_abc")
        self.assertEqual(nums, [99e9])

    def test_table_scale_applied_to_bare_number(self):
        metas = [{"table_scale": 1e6}]
        nums = extract_numbers("The value is 500.", cited_metas=metas)
        self.assertEqual(nums, [500e6])

    def test_inline_scale_overrides_table_scale(self):
        metas = [{"table_scale": 1e3}]
        nums = extract_numbers("The value is 500 million.", cited_metas=metas)
        self.assertEqual(nums, [500e6])

    def test_keyword_context_flips_sign(self):
        nums = extract_numbers("Net loss of $5 million.")
        self.assertEqual(nums, [-5e6])

    def test_empty_text_returns_empty(self):
        self.assertEqual(extract_numbers(""), [])

    def test_none_text_returns_empty(self):
        self.assertEqual(extract_numbers(""), [])

    def test_multiple_numbers(self):
        nums = extract_numbers("Revenue $10B, costs $4B, net $6B.")
        self.assertEqual(nums, [10e9, 4e9, 6e9])


class TestNumericMatch(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(numeric_match("The value is 100.", 100))

    def test_within_tolerance(self):
        self.assertTrue(numeric_match("The value is 105.", 100, tol=0.05))

    def test_outside_tolerance(self):
        self.assertFalse(numeric_match("The value is 120.", 100, tol=0.05))

    def test_small_values_absolute_tolerance(self):
        self.assertTrue(numeric_match("The value is 0.009.", 0.01))

    def test_small_values_outside_tolerance(self):
        self.assertFalse(numeric_match("The value is 0.05.", 0.01))

    def test_scaled_match(self):
        self.assertTrue(numeric_match("$500 million", 500e6))

    def test_no_number_in_answer(self):
        self.assertFalse(numeric_match("Not found.", 100))


class TestRetrievalScore(unittest.TestCase):
    def test_anchor_hit(self):
        retrieved = [
            {"meta": {"anchor": "income_statement", "char_span_start": 0, "char_span_end": 100}}
        ]
        result = retrieval_score(retrieved, gold_chunks=["income_statement"])
        self.assertTrue(result["retrieval_hit"])
        self.assertEqual(result["n_anchor_hits"], 1)

    def test_anchor_miss(self):
        retrieved = [
            {"meta": {"anchor": "balance_sheet", "char_span_start": 0, "char_span_end": 100}}
        ]
        result = retrieval_score(retrieved, gold_chunks=["income_statement"])
        self.assertFalse(result["retrieval_hit"])
        self.assertEqual(result["n_anchor_hits"], 0)

    def test_span_overlap_fallback(self):
        retrieved = [
            {"meta": {"anchor": "none", "char_span_start": 50, "char_span_end": 150}}
        ]
        result = retrieval_score(retrieved,
                                  gold_chunks=[],
                                  gold_spans=[[100, 200]])
        self.assertTrue(result["retrieval_hit"])
        self.assertEqual(result["n_span_hits"], 1)

    def test_no_overlap(self):
        retrieved = [
            {"meta": {"anchor": "none", "char_span_start": 0, "char_span_end": 50}}
        ]
        result = retrieval_score(retrieved,
                                  gold_chunks=[],
                                  gold_spans=[[100, 200]])
        self.assertFalse(result["retrieval_hit"])
        self.assertEqual(result["n_span_hits"], 0)

    def test_no_gold_chunks_or_spans(self):
        retrieved = [
            {"meta": {"anchor": "income_statement", "char_span_start": 0, "char_span_end": 100}}
        ]
        result = retrieval_score(retrieved, gold_chunks=[])
        self.assertFalse(result["retrieval_hit"])

    def test_precision_and_recall(self):
        retrieved = [
            {"meta": {"anchor": "income_statement"}},
            {"meta": {"anchor": "balance_sheet"}},
            {"meta": {"anchor": "unknown"}},
        ]
        result = retrieval_score(retrieved, gold_chunks=["income_statement"])
        self.assertEqual(result["precision"], 1 / 3)
        self.assertEqual(result["recall"], 1.0)

    def test_empty_retrieved(self):
        result = retrieval_score([], gold_chunks=["income_statement"])
        self.assertEqual(result["precision"], 0.0)
        self.assertEqual(result["recall"], 0.0)
        self.assertFalse(result["retrieval_hit"])


class TestRoutingScore(unittest.TestCase):
    def test_corpus_route_correct(self):
        self.assertEqual(routing_score("The answer is $10B.", "corpus"), "correct")

    def test_abstain_route_correct(self):
        self.assertEqual(
            routing_score("Not found in corpus.", "abstain"), "correct"
        )

    def test_web_route_correct(self):
        self.assertEqual(
            routing_score("Found via search. [source: web]", "web"), "correct"
        )

    def test_corpus_when_expected_abstain(self):
        result = routing_score("The answer is $10B.", "abstain")
        self.assertTrue(result.startswith("wrong"))

    def test_abstain_when_expected_corpus(self):
        result = routing_score("Not found in corpus.", "corpus")
        self.assertTrue(result.startswith("wrong"))

    def test_empty_answer_is_wrong(self):
        result = routing_score("", "corpus")
        self.assertTrue(result.startswith("wrong"))

    def test_web_tag_takes_priority_over_abstain(self):
        self.assertEqual(
            routing_score("Not found in corpus. [source: web]", "web"), "correct"
        )


if __name__ == "__main__":
    unittest.main()
