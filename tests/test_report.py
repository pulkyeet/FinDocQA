"""Tests for delta/report.py — report data assembly, rendering, and CLI summary."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from delta.report import (
    build_change_stats,
    build_financial_tables,
    build_report_data,
    build_report_index,
    load_interpretations,
    load_narratives,
    render_cli_summary,
    render_html,
    write_interpretations,
    write_narratives,
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

    xbrl_deltas = {
        "NetIncomeLoss": {
            "FY2024-FY2025": {"old": 96995000000, "new": 93736000000, "pct_change": -3.36},
        },
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "FY2024-FY2025": {"old": 383285000000, "new": 391035000000, "pct_change": 2.02},
        },
    }

    metric_series = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "FY2024": {"value": 383285000000, "pct": None},
            "FY2025": {"value": 391035000000, "pct": 2.02},
        },
        "NetIncomeLoss": {
            "FY2024": {"value": 96995000000, "pct": None},
            "FY2025": {"value": 93736000000, "pct": -3.36},
        },
        "Assets": {
            "FY2024": {"value": 364980000000, "pct": None},
            "FY2025": {"value": 359241000000, "pct": -1.57},
        },
    }

    return records_by_year, interpretations, xbrl_deltas, metric_series


def _make_mock_chapter():
    return {
        "id": "risk",
        "title": "Risk Landscape",
        "subtitle": "What management newly fears",
        "blocks": [
            {"type": "p", "html": 'Apple hardened its AI language in FY2025.'
                                  '<sup class="cite"><a href="#ev-AAPL-item1a_risk-FY2024-FY2025-001">1</a></sup>'},
            {"type": "pullquote", "quote": {
                "y_old": "FY2024", "y_new": "FY2025",
                "old_quote": "competition",
                "new_quote": "AI competition and litigation",
                "section_name": "Risk Factors (1A)",
            }},
        ],
        "footnotes": [{
            "n": 1,
            "change_id": "AAPL-item1a_risk-FY2024-FY2025-001",
            "section_name": "Risk Factors (1A)",
            "y_old": "FY2024", "y_new": "FY2025",
            "summary": "AI competition risk expanded with litigation language.",
            "old_quote": "competition",
            "new_quote": "AI competition and litigation",
        }],
        "n_evidence": 3,
        "n_cited": 1,
        "word_count": 640,
    }


class TestBuildReportData(unittest.TestCase):
    def test_basic_report_shape(self):
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data("AAPL", records, interps, xbrl,
                                   metric_series=series, entity_name="Apple Inc.")

        self.assertEqual(report["ticker"], "AAPL")
        self.assertEqual(report["entity_name"], "Apple Inc.")
        self.assertEqual(report["year_range"], ["FY2024", "FY2025"])
        self.assertIn("generated_at", report)
        self.assertIn("stats", report)
        self.assertIn("financials", report)

    def test_chapters_and_read_time(self):
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data(
            "AAPL", records, interps, xbrl, metric_series=series,
            chapters=[_make_mock_chapter()], exec_summary=["Two hundred words."],
        )
        self.assertEqual(len(report["chapters"]), 1)
        self.assertEqual(report["chapters"][0]["title"], "Risk Landscape")
        # 640 narrative words + 3 summary words at 220 wpm rounds to 3 minutes.
        self.assertEqual(report["read_time"], 3)

    def test_no_chapters_is_safe(self):
        """--no-llm and failed narration must still produce a renderable report."""
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data("AAPL", records, interps, xbrl, metric_series=series)
        self.assertEqual(report["chapters"], [])
        self.assertEqual(report["exec_summary"], [])
        self.assertIsNone(report["financial_narrative"])
        self.assertIn("AAPL", render_html(report))

    def test_empty_records(self):
        report = build_report_data("AAPL", {}, {}, {})
        self.assertEqual(report["year_range"], [])
        self.assertEqual(report["stats"]["total_records"], 0)


class TestBuildChangeStats(unittest.TestCase):
    def test_breakdown_counts(self):
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps)

        by_key = {b["key"]: b["count"] for b in stats["breakdown"]}
        self.assertEqual(by_key["unchanged"], 1)
        self.assertEqual(by_key["modified_minor"], 1)
        self.assertEqual(by_key["modified_major"], 1)
        self.assertEqual(by_key["added"], 1)
        self.assertEqual(stats["total_records"], 4)
        self.assertEqual(stats["total_changed"], 3)

    def test_breakdown_pcts_sum_to_100(self):
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps)
        self.assertAlmostEqual(sum(b["pct"] for b in stats["breakdown"]), 100.0, places=1)

    def test_materiality_tallies(self):
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps)
        self.assertEqual(stats["material"], 1)
        self.assertEqual(stats["notable"], 1)
        self.assertEqual(stats["boilerplate"], 1)
        self.assertEqual(stats["surfaced"], 2)

    def test_unvalidated_excluded_from_materiality(self):
        records, interps, _, _ = _make_mock_data()
        interps["item1a_risk"][0]["_unvalidated"] = True
        stats = build_change_stats(records, interps)
        self.assertEqual(stats["material"], 0)
        self.assertEqual(stats["unvalidated"], 1)

    def test_section_churn_present(self):
        """Churn survives the overhaul, but only at section level."""
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps, churn_min_records=1)

        by_anchor = {s["anchor"]: s for s in stats["sections"]}
        self.assertIn("item1a_risk", by_anchor)
        self.assertIn("item7_mdna", by_anchor)
        self.assertEqual(by_anchor["item1a_risk"]["section_name"], "Risk Factors (1A)")
        self.assertIn("FY2024-FY2025", by_anchor["item1a_risk"]["churn_scores"])
        self.assertIsInstance(by_anchor["item1a_risk"]["max_churn"], float)

    def test_sections_sorted_by_churn(self):
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps, churn_min_records=1)
        churns = [s["max_churn"] for s in stats["sections"]]
        self.assertEqual(churns, sorted(churns, reverse=True))

    def test_thin_sections_omitted_from_churn(self):
        """A stub section with two paragraphs scores 1.00 and is pure noise."""
        records, interps, _, _ = _make_mock_data()
        yp = ("FY2024", "FY2025")
        records[yp].append({
            "ticker": "AAPL", "anchor": "item11_compensation",
            "change_id": "AAPL-item11_compensation-FY2024-FY2025-001",
            "classification": "modified_major", "similarity": 0.6,
            "old_text": "Old.", "new_text": "New.",
        })
        stats = build_change_stats(records, interps, churn_min_records=2)

        reported = {s["anchor"] for s in stats["sections"]}
        self.assertNotIn("item11_compensation", reported)
        # The data is still available, just not surfaced in the table.
        self.assertIn("item11_compensation", {s["anchor"] for s in stats["sections_all"]})
        self.assertEqual(stats["sections_omitted"], 1)

    def test_record_counts_tracked(self):
        records, interps, _, _ = _make_mock_data()
        stats = build_change_stats(records, interps)
        by_anchor = {s["anchor"]: s for s in stats["sections_all"]}
        self.assertEqual(by_anchor["item1a_risk"]["n_records"], 2)
        self.assertEqual(by_anchor["item7_mdna"]["n_records"], 2)


class TestBuildFinancialTables(unittest.TestCase):
    def test_groups_and_every_year_present(self):
        _, _, _, series = _make_mock_data()
        groups = build_financial_tables(series, ["FY2024", "FY2025"])

        titles = [g["title"] for g in groups]
        self.assertIn("Income Statement", titles)
        self.assertIn("Balance Sheet", titles)

        income = next(g for g in groups if g["title"] == "Income Statement")
        # Every year gets its own cell — not just the latest.
        for row in income["rows"]:
            self.assertEqual(len(row["cells"]), 2)

    def test_absolute_value_and_pct_in_cell(self):
        _, _, _, series = _make_mock_data()
        groups = build_financial_tables(series, ["FY2024", "FY2025"])
        income = next(g for g in groups if g["title"] == "Income Statement")
        revenue = next(r for r in income["rows"] if r["label"] == "Revenue")

        self.assertEqual(revenue["cells"][0]["value_str"], "$383.3B")
        self.assertEqual(revenue["cells"][0]["pct_str"], "")   # no prior year
        self.assertEqual(revenue["cells"][1]["value_str"], "$391.0B")
        self.assertEqual(revenue["cells"][1]["pct_str"], "+2.0%")
        self.assertEqual(revenue["cells"][1]["direction"], "up")

    def test_negative_move_is_down(self):
        _, _, _, series = _make_mock_data()
        groups = build_financial_tables(series, ["FY2024", "FY2025"])
        income = next(g for g in groups if g["title"] == "Income Statement")
        ni = next(r for r in income["rows"] if r["label"] == "Net Income")
        self.assertEqual(ni["cells"][1]["direction"], "down")

    def test_tags_without_data_are_dropped(self):
        _, _, _, series = _make_mock_data()
        groups = build_financial_tables(series, ["FY2024", "FY2025"])
        all_tags = {r["tag"] for g in groups for r in g["rows"]}
        self.assertNotIn("GrossProfit", all_tags)

    def test_empty_series_yields_no_groups(self):
        self.assertEqual(build_financial_tables({}, ["FY2024"]), [])


class TestRenderHTML(unittest.TestCase):
    def _full_report(self):
        records, interps, xbrl, series = _make_mock_data()
        return build_report_data(
            "AAPL", records, interps, xbrl, metric_series=series,
            chapters=[_make_mock_chapter()],
            exec_summary=["Apple's filings hardened around AI."],
            entity_name="Apple Inc.",
        )

    def test_render_produces_html(self):
        html = render_html(self._full_report())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("AAPL", html)
        self.assertIn("Apple Inc.", html)

    def test_narrative_prose_rendered(self):
        html = render_html(self._full_report())
        self.assertIn("Apple hardened its AI language", html)
        self.assertIn("Apple's filings hardened around AI.", html)

    def test_citation_and_evidence_drawer(self):
        html = render_html(self._full_report())
        self.assertIn('sup class="cite"', html)
        self.assertIn('id="ev-AAPL-item1a_risk-FY2024-FY2025-001"', html)
        self.assertIn("source cited in this chapter", html)

    def test_pull_quote_rendered(self):
        html = render_html(self._full_report())
        self.assertIn("pull-quote", html)
        self.assertIn("AI competition and litigation", html)

    def test_financial_table_shows_all_years(self):
        html = render_html(self._full_report())
        self.assertIn("Income Statement", html)
        self.assertIn("$383.3B", html)
        self.assertIn("$391.0B", html)
        self.assertIn("(+2.0%)", html)

    def test_dropped_sections_absent(self):
        """Everything from the old change-card wall is gone."""
        html = render_html(self._full_report())
        for dead in ("change-card", "mat-label", "Boilerplate", "boilerplate change"):
            self.assertNotIn(dead, html)

    def test_methodology_and_stats_present(self):
        html = render_html(self._full_report())
        self.assertIn("Methodology", html)
        self.assertIn("What the Engine Found", html)
        self.assertIn("Section churn", html)

    def test_no_findocqa_branding(self):
        html = render_html(self._full_report())
        self.assertNotIn("FinDocQA", html)
        self.assertIn("delta.png", html)


class TestRenderCLISummary(unittest.TestCase):
    def test_structure(self):
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data(
            "AAPL", records, interps, xbrl, metric_series=series,
            chapters=[_make_mock_chapter()], entity_name="Apple Inc.",
        )
        summary = render_cli_summary(report)

        self.assertIn("AAPL", summary)
        self.assertIn("Apple Inc.", summary)
        self.assertIn("Risk Landscape", summary)
        self.assertIn("Change detection", summary)
        self.assertIn("Churn", summary)
        self.assertIn("data/reports/AAPL.html", summary)

    def test_counts_reported(self):
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data("AAPL", records, interps, xbrl, metric_series=series)
        summary = render_cli_summary(report)
        self.assertIn("1 material", summary)
        self.assertIn("1 notable", summary)

    def test_no_chapters(self):
        records, _, xbrl, _ = _make_mock_data()
        report = build_report_data("AAPL", records, {}, xbrl)
        summary = render_cli_summary(report)
        self.assertIn("none composed", summary)


class TestWriteReport(unittest.TestCase):
    def test_write_and_read(self):
        records, interps, xbrl, series = _make_mock_data()
        report = build_report_data("AAPL", records, interps, xbrl, metric_series=series)

        with tempfile.TemporaryDirectory() as tmpdir:
            html = render_html(report)
            path = os.path.join(tmpdir, "AAPL.html")
            with open(path, "w") as f:
                f.write(html)

            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertIn("AAPL", f.read())


class TestPersistence(unittest.TestCase):
    def test_interpretations_round_trip(self):
        _, interps, _, _ = _make_mock_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            import delta.report as rpt
            orig = rpt.DELTA_DIFFS_DIR
            rpt.DELTA_DIFFS_DIR = tmpdir
            try:
                write_interpretations(interps, "AAPL")
                loaded = load_interpretations("AAPL")

                self.assertIn("item1a_risk", loaded)
                self.assertIn("item7_mdna", loaded)
                self.assertEqual(len(loaded["item1a_risk"]), 1)
                self.assertEqual(len(loaded["item7_mdna"]), 2)
            finally:
                rpt.DELTA_DIFFS_DIR = orig

    def test_narrative_round_trip(self):
        """A styling change must be re-renderable without re-running the LLM."""
        chapter = _make_mock_chapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            import delta.report as rpt
            orig = rpt.DELTA_DIFFS_DIR
            rpt.DELTA_DIFFS_DIR = tmpdir
            try:
                write_narratives([chapter], ["Summary text."], None, "AAPL")
                chapters, summary, fin = load_narratives("AAPL")

                self.assertEqual(len(chapters), 1)
                self.assertEqual(chapters[0]["title"], "Risk Landscape")
                self.assertEqual(chapters[0]["footnotes"][0]["n"], 1)
                self.assertEqual(summary, ["Summary text."])
                self.assertIsNone(fin)
            finally:
                rpt.DELTA_DIFFS_DIR = orig

    def test_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import delta.report as rpt
            orig = rpt.DELTA_DIFFS_DIR
            rpt.DELTA_DIFFS_DIR = tmpdir
            try:
                self.assertEqual(load_interpretations("AAPL"), {})
                self.assertEqual(load_narratives("AAPL"), ([], [], None))
            finally:
                rpt.DELTA_DIFFS_DIR = orig


class TestBuildReportIndex(unittest.TestCase):
    def test_index_structure(self):
        html = build_report_index(["AAPL", "MSFT"])
        self.assertIn("Delta Reports", html)
        self.assertIn("AAPL", html)
        self.assertIn("MSFT", html)
        self.assertIn("Apple Inc.", html)
        self.assertIn("Microsoft Corporation", html)
        self.assertNotIn("FinDocQA", html)

    def test_index_empty_tickers(self):
        html = build_report_index([])
        self.assertIn("Delta Reports", html)


if __name__ == "__main__":
    unittest.main()
