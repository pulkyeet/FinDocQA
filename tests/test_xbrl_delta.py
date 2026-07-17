"""Tests for delta/xbrl_delta.py — XBRL numeric delta computation."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.xbrl_delta import (
    get_xbrl_values,
    fiscal_year_value,
    compute_yoy_deltas,
    deltas_for_section,
    format_xbrl_context,
    load_companyfacts,
)


class TestGetXBRLValues(unittest.TestCase):
    def test_aapl_rd_expense(self):
        data = load_companyfacts("AAPL")
        values = get_xbrl_values(data, "ResearchAndDevelopmentExpense")
        self.assertGreater(len(values), 0)
        found = set(v.get("fy", "") for v in values)
        self.assertIn("FY2025", found)
        self.assertIn("FY2024", found)

    def test_unknown_tag(self):
        data = load_companyfacts("AAPL")
        values = get_xbrl_values(data, "NonExistentTagXYZ")
        self.assertEqual(values, [])


class TestFiscalYearValue(unittest.TestCase):
    def test_exact_match(self):
        values = [
            {"end": "2025-09-27", "val": 12345, "unit": "USD", "fy": "FY2025"},
            {"end": "2024-09-28", "val": 9876, "unit": "USD", "fy": "FY2024"},
        ]
        self.assertEqual(fiscal_year_value(values, "FY2025"), 12345)
        self.assertEqual(fiscal_year_value(values, "FY2024"), 9876)

    def test_no_match(self):
        values = [{"end": "2023-09-30", "val": 1000, "unit": "USD", "fy": "FY2023"}]
        self.assertIsNone(fiscal_year_value(values, "FY2025"))


class TestComputeYoYDeltas(unittest.TestCase):
    def test_basic_delta(self):
        data = load_companyfacts("AAPL")
        deltas = compute_yoy_deltas(data, ["ResearchAndDevelopmentExpense"], ["FY2024", "FY2025"])
        self.assertIn("ResearchAndDevelopmentExpense", deltas)
        yp = "FY2024-FY2025"
        self.assertIn(yp, deltas["ResearchAndDevelopmentExpense"])
        d = deltas["ResearchAndDevelopmentExpense"][yp]
        self.assertIn("old", d)
        self.assertIn("new", d)
        self.assertIn("abs_change", d)
        self.assertIn("pct_change", d)

    def test_multi_year(self):
        data = load_companyfacts("AAPL")
        deltas = compute_yoy_deltas(data, ["RevenueFromContractWithCustomerExcludingAssessedTax"], ["FY2023", "FY2024", "FY2025"])
        self.assertIn("RevenueFromContractWithCustomerExcludingAssessedTax", deltas)
        self.assertIn("FY2023-FY2024", deltas["RevenueFromContractWithCustomerExcludingAssessedTax"])
        self.assertIn("FY2024-FY2025", deltas["RevenueFromContractWithCustomerExcludingAssessedTax"])

    def test_empty_tag(self):
        data = load_companyfacts("AAPL")
        deltas = compute_yoy_deltas(data, ["NonExistentXYZ"], ["FY2024", "FY2025"])
        self.assertEqual(deltas, {})


class TestDeltasForSection(unittest.TestCase):
    def test_income_statement_filter(self):
        deltas = {
            "Revenues": {"FY2024-FY2025": {"old": 100, "new": 120}},
            "Assets": {"FY2024-FY2025": {"old": 200, "new": 300}},
        }
        result = deltas_for_section(deltas, "income_statement")
        self.assertIn("Revenues", result)
        self.assertNotIn("Assets", result)

    def test_no_matching_tags(self):
        deltas = {"Assets": {"FY2024-FY2025": {"old": 200, "new": 300}}}
        result = deltas_for_section(deltas, "income_statement")
        self.assertEqual(result, {})


class TestFormatXBRLContext(unittest.TestCase):
    def test_formatted_output(self):
        deltas = {
            "Revenues": {"FY2024-FY2025": {"old": 380000000000, "new": 390000000000, "pct_change": 2.63}},
        }
        text = format_xbrl_context(deltas)
        self.assertIn("Revenues", text)
        self.assertIn("FY2024-FY2025", text)
        self.assertIn("+2.6%", text)

    def test_empty_deltas(self):
        text = format_xbrl_context({})
        self.assertIn("No XBRL", text)


if __name__ == "__main__":
    unittest.main()
