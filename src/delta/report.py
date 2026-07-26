"""Stage 9: Report assembly — narrative HTML (Jinja2) and CLI summary.

The report is an essay built from the diff, not a rendering of the diff. It
consumes composed chapter narratives (stage 8), the audited XBRL series, and
the raw diff records — the last only to report *how much* changed, never as
reading material.
"""

import json
import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from anchors import SECTION_NAMES
from config import (
    CHURN_MIN_RECORDS, DELTA_DIFFS_DIR, DELTA_REPORTS_DIR,
    WORDS_PER_MINUTE, XBRL_STATEMENT_GROUPS,
)
from delta.diff import compute_churn_score

# Human-readable labels for the XBRL concept tags surfaced in the report.
XBRL_LABELS = {
    "Revenues": "Revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenue",
    "ResearchAndDevelopmentExpense": "R&D Expense",
    "CostOfGoodsAndServicesSold": "Cost of Revenue",
    "GrossProfit": "Gross Profit",
    "OperatingIncomeLoss": "Operating Income",
    "NetIncomeLoss": "Net Income",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes": "Pre-Tax Income",
    "IncomeTaxExpenseBenefit": "Income Tax",
    "SellingGeneralAndAdministrativeExpense": "SG&A",
    "EarningsPerShareBasic": "EPS (Basic)",
    "EarningsPerShareDiluted": "EPS (Diluted)",
    "NetCashProvidedByUsedInOperatingActivities": "Operating Cash Flow",
    "NetCashProvidedByUsedInInvestingActivities": "Investing Cash Flow",
    "NetCashProvidedByUsedInFinancingActivities": "Financing Cash Flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "Capital Expenditure",
    "PaymentsForRepurchaseOfCommonStock": "Share Repurchases",
    "PaymentsOfDividends": "Dividends Paid",
    "Assets": "Total Assets",
    "Liabilities": "Total Liabilities",
    "StockholdersEquity": "Stockholders' Equity",
    "LongTermDebtNoncurrent": "Long-Term Debt",
    "CashAndCashEquivalentsAtCarryingValue": "Cash & Equivalents",
    "AccountsReceivableNetCurrent": "Accounts Receivable",
    "AccountsReceivableNet": "Accounts Receivable",
    "InventoryNet": "Inventory",
    "PropertyPlantAndEquipmentNet": "Property & Equipment",
}

# EPS-style tags are per-share dollars, not aggregate — format them plainly.
_PER_SHARE_TAGS = {"EarningsPerShareBasic", "EarningsPerShareDiluted"}

# Tags where a rising number is a cash outflow, not an improvement, so the
# report must not paint the increase green.
_INVERTED_TAGS = {
    "CostOfGoodsAndServicesSold", "IncomeTaxExpenseBenefit",
    "SellingGeneralAndAdministrativeExpense", "Liabilities",
    "LongTermDebtNoncurrent",
}

CLASSIFICATION_LABELS = {
    "unchanged": "Unchanged",
    "modified_minor": "Minor revision",
    "modified_major": "Major revision",
    "added": "Newly added",
    "removed": "Removed",
}


def _fmt_money(v, tag=None) -> str:
    """Format a financial value compactly ($391.0B, $1.2M, -$4.3B, $6.13)."""
    if v is None:
        return "—"
    v = float(v)
    if tag in _PER_SHARE_TAGS:
        return f"${v:,.2f}"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:,.0f}"


_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "templates")
_STATIC_DIR = os.path.join(os.path.dirname(_TEMPLATE_DIR), "static")


def _static_version(rel_path: str) -> str:
    """Cache-busting token for a /static asset — see web/app.py:static_version.

    Reports are pre-rendered offline, so this bakes in the mtime as of the
    build rather than computing it per request; a rebuild is what refreshes it.
    """
    path = os.path.join(_STATIC_DIR, rel_path)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


def build_financial_tables(metric_series: dict, years: list[str]) -> list[dict]:
    """One table per financial statement: every year's absolute value, % in brackets.

    Rows whose tag has no data for this filer are dropped rather than rendered
    as a row of dashes.
    """
    groups = []
    for title, tags in XBRL_STATEMENT_GROUPS:
        rows = []
        for tag in tags:
            series = metric_series.get(tag)
            if not series:
                continue
            cells = []
            has_value = False
            for fy in years:
                d = series.get(fy) or {}
                val, pct = d.get("value"), d.get("pct")
                if val is not None:
                    has_value = True
                direction = ""
                if pct is not None and abs(pct) >= 0.05:
                    rising = pct > 0
                    good = not rising if tag in _INVERTED_TAGS else rising
                    direction = "up" if good else "down"
                cells.append({
                    "value_str": _fmt_money(val, tag),
                    "pct": pct,
                    "pct_str": f"{pct:+.1f}%" if pct is not None else "",
                    "direction": direction,
                })
            if has_value:
                rows.append({
                    "label": XBRL_LABELS.get(tag, tag),
                    "tag": tag,
                    "cells": cells,
                })
        if rows:
            groups.append({"title": title, "rows": rows})
    return groups


def build_change_stats(records_by_year: dict, interpretations: dict,
                       churn_min_records: int = CHURN_MIN_RECORDS) -> dict:
    """The 'how much changed' numbers: classification counts and section churn.

    Churn is reported at section level only — paragraph-level churn was noise.
    Sections thinner than churn_min_records are computed but not surfaced.
    """
    year_pairs = sorted(records_by_year.keys())
    totals = {}
    by_year = []

    for y_old, y_new in year_pairs:
        records = records_by_year[(y_old, y_new)]
        counts = {}
        for r in records:
            cls = r.get("classification", "unknown")
            counts[cls] = counts.get(cls, 0) + 1
            totals[cls] = totals.get(cls, 0) + 1
        by_year.append({
            "year_pair": f"{y_old} → {y_new}",
            "counts": counts,
            "total": len(records),
        })

    anchors = sorted({r.get("anchor") for recs in records_by_year.values()
                      for r in recs if r.get("anchor")})

    sections = []
    for anchor in anchors:
        churn_scores = {}
        n_records = 0
        for y_old, y_new in year_pairs:
            recs = [r for r in records_by_year[(y_old, y_new)]
                    if r.get("anchor") == anchor]
            n_records += len(recs)
            matched = [r for r in recs
                       if r.get("classification") not in ("added", "removed")]
            classifications = [r["classification"] for r in matched]
            score = compute_churn_score(
                matched if matched else [{"old_text": "", "new_text": ""}],
                classifications if classifications else ["unchanged"],
            )
            churn_scores[f"{y_old}-{y_new}"] = round(score, 4)
        vals = [v for v in churn_scores.values() if v is not None]
        sections.append({
            "anchor": anchor,
            "section_name": SECTION_NAMES.get(anchor, anchor),
            "churn_scores": churn_scores,
            "n_records": n_records,
            "max_churn": max(vals) if vals else 0.0,
            "avg_churn": round(sum(vals) / len(vals), 4) if vals else 0.0,
        })
    sections.sort(key=lambda s: s["max_churn"], reverse=True)

    reported = [s for s in sections if s["n_records"] >= churn_min_records]
    n_omitted = len(sections) - len(reported)

    n_material = n_notable = n_boilerplate = n_unvalidated = 0
    for interps in interpretations.values():
        for ir in interps:
            if ir.get("_unvalidated"):
                n_unvalidated += 1
                continue
            m = ir.get("materiality")
            if m == "material":
                n_material += 1
            elif m == "notable":
                n_notable += 1
            elif m == "boilerplate":
                n_boilerplate += 1

    n_guard = sum(1 for recs in records_by_year.values()
                  for r in recs if r.get("numeric_guard"))

    ordered = ["unchanged", "modified_minor", "modified_major", "added", "removed"]
    total_records = sum(totals.values())
    breakdown = []
    for cls in ordered:
        n = totals.get(cls, 0)
        if not n:
            continue
        breakdown.append({
            "key": cls,
            "label": CLASSIFICATION_LABELS.get(cls, cls),
            "count": n,
            "pct": round(n / total_records * 100, 1) if total_records else 0.0,
        })

    return {
        "year_pairs": [f"{a}-{b}" for a, b in year_pairs],
        "year_pair_labels": [f"{a[2:]}→{b[2:]}" for a, b in year_pairs],
        "breakdown": breakdown,
        "by_year": by_year,
        "sections": reported,
        "sections_all": sections,
        "sections_omitted": n_omitted,
        "churn_min_records": churn_min_records,
        "total_records": total_records,
        "total_changed": total_records - totals.get("unchanged", 0),
        "material": n_material,
        "notable": n_notable,
        "boilerplate": n_boilerplate,
        "unvalidated": n_unvalidated,
        "guard": n_guard,
        "surfaced": n_material + n_notable,
    }


def build_report_data(ticker, records_by_year, interpretations, xbrl_deltas,
                      metric_series=None, chapters=None, exec_summary=None,
                      financial_narrative=None, entity_name="") -> dict:
    """Assemble the full narrative report dict.

    Args:
        ticker: e.g. "AAPL"
        records_by_year: {(y_old, y_new): [diff_records]}
        interpretations: {anchor: [interpretation_records]} — for the stats block
        xbrl_deltas: {tag: {year_pair: {...}}} — kept for the numeric guard trail
        metric_series: {tag: {fy: {value, pct}}} from build_metric_series()
        chapters: composed narrative chapters from delta.narrate
        exec_summary: list of paragraph HTML strings
        entity_name: e.g. "Apple Inc."
    """
    year_pairs = sorted(records_by_year.keys())
    all_years = set()
    for y_old, y_new in year_pairs:
        all_years.update((y_old, y_new))
    year_range = sorted(all_years)

    chapters = chapters or []
    exec_summary = exec_summary or []

    stats = build_change_stats(records_by_year, interpretations)
    financials = build_financial_tables(metric_series or {}, year_range)

    narrative_words = sum(ch.get("word_count", 0) for ch in chapters)
    narrative_words += sum(len(p.split()) for p in exec_summary)
    if financial_narrative:
        narrative_words += financial_narrative.get("word_count", 0)
    read_time = max(1, round(narrative_words / WORDS_PER_MINUTE))

    return {
        "ticker": ticker,
        "entity_name": entity_name or ticker,
        "year_range": year_range,
        "_year_pairs": year_pairs,
        "exec_summary": exec_summary,
        "chapters": chapters,
        "financials": financials,
        "financial_narrative": financial_narrative,
        "stats": stats,
        "word_count": narrative_words,
        "read_time": read_time,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render_html(report_data, template_dir=None):
    """Render the Delta report as HTML using Jinja2."""
    if template_dir is None:
        template_dir = _TEMPLATE_DIR

    env = Environment(loader=FileSystemLoader(template_dir))
    env.globals["static_v"] = _static_version
    template = env.get_template("report.html")
    return template.render(report=report_data)


def render_cli_summary(report_data) -> str:
    """Render the CLI text summary for a report."""
    lines = []
    ticker = report_data["ticker"]
    entity = report_data.get("entity_name", ticker)
    stats = report_data["stats"]
    yr_start = report_data["year_range"][0]
    yr_end = report_data["year_range"][-1]

    lines.append(f"\n{'=' * 70}")
    lines.append(f"  {ticker} ({entity}) — Delta Change Report")
    lines.append(f"  {yr_start} → {yr_end}   ·   {report_data['read_time']} min read "
                 f"({report_data['word_count']:,} words)")
    lines.append(f"{'=' * 70}")

    lines.append("\n  Chapters")
    lines.append(f"  {'-' * 66}")
    if report_data["exec_summary"]:
        lines.append(f"  {'Executive Summary':<34} "
                     f"{sum(len(p.split()) for p in report_data['exec_summary']):>5} words")
    for ch in report_data["chapters"]:
        lines.append(f"  {ch['title']:<34} {ch['word_count']:>5} words   "
                     f"{ch['n_cited']}/{ch['n_evidence']} sources cited")
    if not report_data["chapters"]:
        lines.append("  (none composed — run without --no-llm)")

    lines.append(f"\n  Change detection")
    lines.append(f"  {'-' * 66}")
    for b in stats["breakdown"]:
        bar = "█" * int(b["pct"] / 4)
        lines.append(f"  {b['label']:<20} {b['count']:>6}  {b['pct']:>5.1f}%  {bar}")
    lines.append(f"  {'TOTAL':<20} {stats['total_records']:>6}")
    lines.append(f"\n  Interpreted: {stats['material']} material, "
                 f"{stats['notable']} notable, {stats['boilerplate']} boilerplate")
    lines.append(f"  Numeric guard surfaced: {stats['guard']}")
    if stats["unvalidated"]:
        lines.append(f"  ⚠ {stats['unvalidated']} unvalidated (excluded from prose)")

    lines.append("\n  Churn — top sections")
    lines.append(f"  {'-' * 66}")
    for sec in stats["sections"][:8]:
        bar = "█" * min(int(sec["max_churn"] * 20), 20)
        lines.append(f"  {sec['section_name']:<34} {sec['max_churn']:.2f} {bar}")

    lines.append(f"\n  Report: {DELTA_REPORTS_DIR}/{ticker}.html")
    lines.append(f"{'=' * 70}")

    return "\n".join(lines)


def write_report(ticker, html, suffix=""):
    """Write rendered HTML to data/reports/{ticker}{suffix}.html."""
    os.makedirs(DELTA_REPORTS_DIR, exist_ok=True)
    path = os.path.join(DELTA_REPORTS_DIR, f"{ticker}{suffix}.html")
    with open(path, "w") as f:
        f.write(html)
    return path


def write_interpretations(interpretations, ticker):
    """Persist interpretations to data/diffs/{ticker}/_interpretations.jsonl."""
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"
    os.makedirs(output_dir, exist_ok=True)

    interp_path = os.path.join(output_dir, "_interpretations.jsonl")
    with open(interp_path, "w") as f:
        for anchor, interps in sorted(interpretations.items()):
            for ir in interps:
                ir["_anchor"] = anchor
                f.write(json.dumps(ir) + "\n")
    return interp_path


def write_narratives(chapters, exec_summary, financial_narrative, ticker):
    """Persist composed narrative so the report can be re-rendered without an LLM."""
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "_narrative.json")
    with open(path, "w") as f:
        json.dump({
            "chapters": chapters,
            "exec_summary": exec_summary,
            "financial_narrative": financial_narrative,
        }, f)
    return path


def load_narratives(ticker):
    """Load persisted narrative. Returns (chapters, exec_summary, financial_narrative)."""
    path = os.path.join(DELTA_DIFFS_DIR, ticker, "_narrative.json")
    if not os.path.exists(path):
        return [], [], None
    with open(path) as f:
        data = json.load(f)
    return (data.get("chapters", []), data.get("exec_summary", []),
            data.get("financial_narrative"))


def load_interpretations(ticker):
    """Load persisted interpretations. Returns {anchor: [records]}."""
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"

    interpretations = {}
    interp_path = os.path.join(output_dir, "_interpretations.jsonl")
    if os.path.exists(interp_path):
        with open(interp_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    ir = json.loads(line)
                    anchor = ir.pop("_anchor", "unknown")
                    interpretations.setdefault(anchor, []).append(ir)

    return interpretations


def build_report_index(tickers, report_dir=None):
    """Build data/reports/index.html listing all ticker reports."""
    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    env.globals["static_v"] = _static_version
    tpl = env.get_template("report_index.html")

    names = {
        "AAPL": "Apple Inc.",
        "AMZN": "Amazon.com, Inc.",
        "GOOGL": "Alphabet Inc.",
        "META": "Meta Platforms, Inc.",
        "MSFT": "Microsoft Corporation",
        "NVDA": "NVIDIA Corporation",
        "TSLA": "Tesla, Inc.",
    }

    return tpl.render(tickers=sorted(tickers), names=names, static_prefix="")
