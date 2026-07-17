import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from anchors import (
    item_header_to_anchor,
    table_heading_to_anchor,
    ANCHOR_VOCABULARY,
)


class TestItemHeaderToAnchor(unittest.TestCase):
    def test_item1_business(self):
        result = item_header_to_anchor("Item 1. Business")
        self.assertEqual(result, "item1_business")

    def test_item1a_risk(self):
        result = item_header_to_anchor("Item 1A. Risk Factors")
        self.assertEqual(result, "item1a_risk")

    def test_item7_mdna(self):
        result = item_header_to_anchor("Item 7. Management's Discussion and Analysis")
        self.assertEqual(result, "item7_mdna")

    def test_item7a_market_risk(self):
        result = item_header_to_anchor("Item 7A. Quantitative and Qualitative Disclosures")
        self.assertEqual(result, "item7a_market_risk")

    def test_item8_financials(self):
        result = item_header_to_anchor("Item 8. Financial Statements")
        self.assertEqual(result, "item8_financials")

    def test_item9a_controls(self):
        result = item_header_to_anchor("Item 9A. Controls and Procedures")
        self.assertEqual(result, "item9a_controls")

    def test_item15_exhibits(self):
        result = item_header_to_anchor("Item 15. Exhibits")
        self.assertEqual(result, "item15_exhibits")

    def test_fallback_to_unknown(self):
        result = item_header_to_anchor("Item 99. Something Unknown")
        self.assertEqual(result, "item99_unknown")

    def test_no_item_number_returns_unknown(self):
        result = item_header_to_anchor("Some random header")
        self.assertEqual(result, "unknown")

    def test_case_insensitive(self):
        result = item_header_to_anchor("ITEM 1. BUSINESS")
        self.assertEqual(result, "item1_business")

    def test_item16_summary(self):
        result = item_header_to_anchor("Item 16. Summary")
        self.assertEqual(result, "item16_summary")


class TestTableHeadingToAnchor(unittest.TestCase):
    def test_income_statement(self):
        result = table_heading_to_anchor(
            "CONSOLIDATED STATEMENTS OF OPERATIONS", "item8_financials"
        )
        self.assertEqual(result, "income_statement")

    def test_income_statement_alt(self):
        result = table_heading_to_anchor(
            "CONSOLIDATED STATEMENTS OF INCOME", "item8_financials"
        )
        self.assertEqual(result, "income_statement")

    def test_balance_sheet(self):
        result = table_heading_to_anchor(
            "CONSOLIDATED BALANCE SHEETS", "item8_financials"
        )
        self.assertEqual(result, "balance_sheet")

    def test_cash_flow(self):
        result = table_heading_to_anchor(
            "CONSOLIDATED STATEMENTS OF CASH FLOWS", "item8_financials"
        )
        self.assertEqual(result, "cash_flow")

    def test_stockholders_equity(self):
        result = table_heading_to_anchor(
            "CONSOLIDATED STATEMENTS OF STOCKHOLDERS' EQUITY", "item8_financials"
        )
        self.assertEqual(result, "stockholders_equity")

    def test_notes_to_financials(self):
        result = table_heading_to_anchor(
            "Notes to Consolidated Financial Statements", "item8_financials"
        )
        self.assertEqual(result, "notes_to_financials")

    def test_fallback_anchor(self):
        result = table_heading_to_anchor(
            "Some random table caption", "item7_mdna"
        )
        self.assertEqual(result, "item7_mdna")

    def test_income_operations_fallback(self):
        result = table_heading_to_anchor(
            "Consolidated Operations and Income Details", "item8_financials"
        )
        self.assertEqual(result, "income_statement")


class TestAnchorVocabulary(unittest.TestCase):
    def test_all_known_anchors_in_vocabulary(self):
        """item_header_to_anchor should only return anchors in ANCHOR_VOCABULARY."""
        test_headers = [
            "Item 1. Business",
            "Item 1A. Risk Factors",
            "Item 1B. Unresolved",
            "Item 1C. Cybersecurity",
            "Item 2. Properties",
            "Item 3. Legal",
            "Item 4. Safety",
            "Item 5. Market",
            "Item 6. Reserved",
            "Item 7. Management's Discussion",
            "Item 7A. Quantitative",
            "Item 8. Financial Statements",
            "Item 9. Disagreements",
            "Item 9A. Controls",
            "Item 9B. Other",
            "Item 9C. Foreign",
            "Item 10. Directors",
            "Item 11. Compensation",
            "Item 12. Security",
            "Item 13. Relationships",
            "Item 14. Accountant",
            "Item 15. Exhibits",
            "Item 16. Summary",
        ]
        for h in test_headers:
            anchor = item_header_to_anchor(h)
            self.assertIn(
                anchor, ANCHOR_VOCABULARY,
                f"Anchor '{anchor}' from header '{h}' not in ANCHOR_VOCABULARY"
            )


if __name__ == "__main__":
    unittest.main()
