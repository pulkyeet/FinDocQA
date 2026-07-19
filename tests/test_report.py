"""Tests for delta/report.py — report data assembly, rendering, and CLI summary."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.report import (
    build_report_data,
    build_report_index,
    load_interpretations,
    render_cli_summary,
    render_html,
    write_interpretations,
    write_report,
)


def _make_mock_data():
    """Build mock pipeline data that mirrors what run_delta() produces."""
    records_by_year = {
        ("FY2024", "FY2025"): [
            {
                "ticker": "AAPL", "anchor": "item1a_risk",
                "year_pair": ["FY2024", "FY2025"],
                "change_id": "AAPL-item1a_risk-FY2024-FY2025-001",
                "classification": "modified_major",
                "similarity": 0.65,
                "old_para_idx": 0, "new_para_idx": 0,
                "old_text": "The Company faces risks from competition.",
                "new_text": "The Company faces risks from AI competition and litigation.",
                "word_delta": {"added": ["AI", "litigation"], "removed": []},
            },
            {
                "ticker": "AAPL", "anchor": "item1a_risk",
                "year_pair": ["FY2024", "FY2025"],
                "change_id": "AAPL-item1a_risk-FY2024-FY2025-002",
                "classification": "unchanged",
                "similarity": 0.97,
                "old_para_idx": 1, "new_para_idx": 1,
                "old_text": "The compliance landscape is stable.",
                "new_text": "The compliance landscape is stable.",
                "word_delta": {"added": [], "removed": []},
            },
            {
                "ticker": "AAPL", "anchor": "item7_mdna",
                "year_pair": ["FY2024", "FY2025"],
                "change_id": "AAPL-item7_mdna-FY2024-FY2025-001",
                "classification": "modified_minor",
                "similarity": 0.88,
                "old_para_idx": 0, "new_para_idx": 0,
                "old_text": "Net sales were $383B.",
                "new_text": "Net sales were $391B.",
                "word_delta": {"added": ["391"], "removed": ["383"]},
            },
            {
                "ticker": "AAPL", "anchor": "item7_mdna",
                "year_pair": ["FY2024", "FY2025"],
                "change_id": "AAPL-item7_mdna-FY2024-FY2025-002",
                "classification": "added",
                "similarity": 0.0,
                "old_para_idx": -1, "new_para_idx": 5,
                "old_text": "",
                "new_text": "New segment disclosure for wearables.",
                "word_delta": {"added": ["New", "segment", "disclosure"], "removed": []},
            },
        ]
    }

    interpretations = {
        "item1a_risk": [
            {
                "change_id": "AAPL-item1a_risk-FY2024-FY2025-001",
                "change_type": "expanded",
                "materiality": "material",
                "summary": "AI competition risk expanded with litigation language.",
                "why_it_matters": "First litigation framing of AI risk.",
                "old_quote": "competition",
                "new_quote": "AI competition and litigation",
                "_y_old": "FY2024", "_y_new": "FY2025",
            },
        ],
        "item7_mdna": [
            {
                "change_id": "AAPL-item7_mdna-FY2024-FY2025-001",
                "change_type": "reworded",
                "materiality": "boilerplate",
                "summary": "Sales figure updated for new fiscal year.",
                "why_it_matters": None,
                "old_quote": "$383B",
                "new_quote": "$391B",
                "_y_old": "FY2024", "_y_new": "FY2025",
            },
            {
                "change_id": "AAPL-item7_mdna-FY2024-FY2025-002",
                "change_type": "added",
                "materiality": "notable",
                "summary": "New wearables segment disclosure added.",
                "why_it_matters": "Reflects Apple Watch and AirPods as separate reporting.",
                "old_quote": "",
                "new_quote": "New segment disclosure for wearables",
                "_y_old": "FY2024", "_y_new": "FY2025",
            },
        ],
    }

    trends = {
        "item1a_risk": "Risk factors expanded significantly between FY2024-FY2025.",
        "item7_mdna": "MD&A continued to emphasize services growth.",
    }

    xbrl_deltas = {
        "NetIncomeLoss": {
            "FY2024-FY2025": {"old": 96995000000, "new": 93736000000, "pct_change": -3.36},
        },
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "FY2024-FY2025": {"old": 383285000000, "new": 391035000000, "pct_change": 2.02},
        },
    }

    return records_by_year, interpretations, trends, xbrl_deltas


class TestBuildReportData(unittest.TestCase):
    def test_basic_report_shape(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl, "Apple Inc.")

        self.assertEqual(report["ticker"], "AAPL")
        self.assertEqual(report["entity_name"], "Apple Inc.")
        self.assertEqual(report["year_range"], ["FY2024", "FY2025"])
        self.assertIn("generated_at", report)

    def test_sections_present(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        anchors = [s["anchor"] for s in report["sections"]]
        self.assertIn("item1a_risk", anchors)
        self.assertIn("item7_mdna", anchors)

    def test_churn_scores(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        for sec in report["sections"]:
            self.assertIn("FY2024-FY2025", sec["churn_scores"])
            self.assertIsInstance(sec["churn_scores"]["FY2024-FY2025"], float)

    def test_section_names(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        names = {s["anchor"]: s["section_name"] for s in report["sections"]}
        self.assertEqual(names["item1a_risk"], "Risk Factors (1A)")
        self.assertEqual(names["item7_mdna"], "MD&A (7)")

    def test_changes_attached(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        risk_sec = next(s for s in report["sections"] if s["anchor"] == "item1a_risk")
        self.assertGreaterEqual(len(risk_sec["changes"]), 1)

        mdna_sec = next(s for s in report["sections"] if s["anchor"] == "item7_mdna")
        self.assertGreaterEqual(len(mdna_sec["changes"]), 2)

    def test_trends_attached(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        risk_sec = next(s for s in report["sections"] if s["anchor"] == "item1a_risk")
        self.assertIn("Risk factors expanded", risk_sec["trend_narrative"])

    def test_xbrl_report(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        self.assertIn("_year_pairs", report["xbrl_deltas"])
        self.assertIn("_tag_order", report["xbrl_deltas"])
        self.assertIn("NetIncomeLoss", report["xbrl_deltas"])
        self.assertIn("RevenueFromContractWithCustomerExcludingAssessedTax", report["xbrl_deltas"])

    def test_empty_interpretations(self):
        records, _, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, {}, trends, xbrl)
        for sec in report["sections"]:
            # No interpretation data, but sections should still exist with zero changes
            self.assertEqual(sec["changes"], [])

    def test_empty_records(self):
        report = build_report_data("AAPL", {}, {}, {}, {}, "Apple Inc.")
        self.assertEqual(report["year_range"], [])
        self.assertEqual(report["sections"], [])


class TestRenderHTML(unittest.TestCase):
    def test_render_produces_html(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl, "Apple Inc.")
        html = render_html(report)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("AAPL", html)
        self.assertIn("Apple Inc.", html)
        self.assertIn("Risk Factors", html)

    def test_material_changes_in_html(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)
        html = render_html(report)

        self.assertIn("AI competition", html)
        self.assertIn("Material Changes", html)

    def test_xbrl_table_in_html(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)
        html = render_html(report)

        self.assertIn("Key Financial Metrics", html)
        self.assertIn("NetIncomeLoss", html)

    def test_unvalidated_flag(self):
        records, interps, trends, xbrl = _make_mock_data()
        interps["item1a_risk"][0]["_unvalidated"] = True
        report = build_report_data("AAPL", records, interps, trends, xbrl)
        html = render_html(report)
        self.assertIn("unvalidated", html)


class TestRenderCLISummary(unittest.TestCase):
    def test_structure(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl, "Apple Inc.")
        summary = render_cli_summary(report)

        self.assertIn("AAPL", summary)
        self.assertIn("Apple Inc.", summary)
        self.assertIn("Churn Scores", summary)
        self.assertIn("Material changes", summary)
        self.assertIn("Risk Factors", summary)
        self.assertIn("data/reports/AAPL.html", summary)

    def test_material_count(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)
        summary = render_cli_summary(report)

        self.assertIn("Material changes: 1", summary)
        self.assertIn("Notable: 1", summary)

    def test_no_interpretations(self):
        records, _, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, {}, {}, {})
        summary = render_cli_summary(report)
        self.assertIn("Material changes: 0", summary)


class TestWriteReport(unittest.TestCase):
    def test_write_and_read(self):
        records, interps, trends, xbrl = _make_mock_data()
        report = build_report_data("AAPL", records, interps, trends, xbrl)

        with tempfile.TemporaryDirectory() as tmpdir:
            html = render_html(report)
            path = os.path.join(tmpdir, "AAPL.html")
            with open(path, "w") as f:
                f.write(html)

            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                content = f.read()
                self.assertIn("AAPL", content)


class TestInterpretationsPersistence(unittest.TestCase):
    def test_round_trip(self):
        _, interps, trends, _ = _make_mock_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            import delta.report as rpt
            orig_diffs_dir = rpt.DELTA_DIFFS_DIR
            rpt.DELTA_DIFFS_DIR = tmpdir

            try:
                write_interpretations(interps, trends, "AAPL",
                                      [("FY2024", "FY2025")])

                loaded_interps, loaded_trends = load_interpretations("AAPL")

                self.assertIn("item1a_risk", loaded_interps)
                self.assertIn("item7_mdna", loaded_interps)
                self.assertEqual(
                    len(loaded_interps["item1a_risk"]), 1
                )
                self.assertEqual(
                    len(loaded_interps["item7_mdna"]), 2
                )
                self.assertIn("item1a_risk", loaded_trends)
                self.assertIn("Risk factors expanded", loaded_trends["item1a_risk"])
            finally:
                rpt.DELTA_DIFFS_DIR = orig_diffs_dir

    def test_missing_interpretations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import delta.report as rpt
            orig_diffs_dir = rpt.DELTA_DIFFS_DIR
            rpt.DELTA_DIFFS_DIR = tmpdir

            try:
                interps, trends = load_interpretations("AAPL")
                self.assertEqual(interps, {})
                self.assertEqual(trends, {})
            finally:
                rpt.DELTA_DIFFS_DIR = orig_diffs_dir


class TestBuildReportIndex(unittest.TestCase):
    def test_index_structure(self):
        html = build_report_index(["AAPL", "MSFT"])
        self.assertIn("FinDocQA Delta", html)
        self.assertIn("AAPL", html)
        self.assertIn("MSFT", html)
        self.assertIn("Reports", html)
        self.assertIn("Apple Inc.", html)
        self.assertIn("Microsoft Corporation", html)
        self.assertIn("report", html.lower())

    def test_index_empty_tickers(self):
        html = build_report_index([])
        self.assertIn("FinDocQA Delta", html)


if __name__ == "__main__":
    unittest.main()
