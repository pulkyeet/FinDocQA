"""Stage 9: Report rendering — HTML (Jinja2) and CLI summary.

Consumes diff records + interpretations + XBRL deltas + trend narratives
and produces the full report per ARCHITECTURE §2.6.
"""

import json
import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from config import DELTA_DIFFS_DIR, DELTA_REPORTS_DIR
from delta.diff import compute_churn_score, classification_counts

SECTION_NAMES = {
    "item1_business": "Business (1)",
    "item1a_risk": "Risk Factors (1A)",
    "item1b_unresolved": "Unresolved Comments (1B)",
    "item1c_cybersecurity": "Cybersecurity (1C)",
    "item2_properties": "Properties (2)",
    "item3_legal": "Legal Proceedings (3)",
    "item4_safety": "Mine Safety (4)",
    "item5_market": "Market (5)",
    "item6_reserved": "Reserved (6)",
    "item7_mdna": "MD&A (7)",
    "item7a_market_risk": "Market Risk (7A)",
    "item8_financials": "Financials (8)",
    "item9_changes": "Changes in Accountants (9)",
    "item9a_controls": "Controls (9A)",
    "item9b_other": "Other Information (9B)",
    "item9c_foreign": "Foreign Jurisdictions (9C)",
    "item10_governance": "Governance (10)",
    "item11_compensation": "Compensation (11)",
    "item12_equity": "Equity (12)",
    "item13_relationships": "Relationships (13)",
    "item14_accountant": "Accountant Fees (14)",
    "item15_exhibits": "Exhibits (15)",
    "item16_summary": "Summary (16)",
    "income_statement": "Income Statement",
    "balance_sheet": "Balance Sheet",
    "cash_flow": "Cash Flow",
    "stockholders_equity": "Stockholders' Equity",
    "notes_to_financials": "Notes to Financials",
}

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
    "Assets": "Total Assets",
    "Liabilities": "Total Liabilities",
    "StockholdersEquity": "Stockholders' Equity",
    "LongTermDebtNoncurrent": "Long-Term Debt",
    "CashAndCashEquivalentsAtCarryingValue": "Cash & Equivalents",
    "AccountsReceivableNet": "Accounts Receivable",
    "InventoryNet": "Inventory",
    "PropertyPlantAndEquipmentNet": "Property & Equipment",
}

# EPS-style tags are per-share dollars, not aggregate — format them plainly.
_PER_SHARE_TAGS = {"EarningsPerShareBasic", "EarningsPerShareDiluted"}


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


def build_report_data(ticker, records_by_year, interpretations, trends,
                      xbrl_deltas, entity_name="") -> dict:
    """Assemble the full report dict per ARCHITECTURE §2.6.

    Args:
        ticker: e.g. "AAPL"
        records_by_year: {(y_old, y_new): [diff_records]}
        interpretations: {anchor: [interpretation_records]}
        trends: {anchor: trend_text}
        xbrl_deltas: {tag: {year_pair_str: {old, new, pct_change, ...}}}
        entity_name: e.g. "Apple Inc."

    Returns the full report dict.
    """
    year_pairs = sorted(records_by_year.keys())
    all_years = set()
    for y_old, y_new in year_pairs:
        all_years.add(y_old)
        all_years.add(y_new)
    year_range = sorted(all_years)

    sections = []
    all_anchors = set()

    # Numeric guard lives on the diff record; join it onto interpretations by
    # change_id so the report can show why an otherwise-identical paragraph was
    # surfaced.
    guard_by_change_id = {}
    for records in records_by_year.values():
        for r in records:
            a = r.get("anchor")
            if a:
                all_anchors.add(a)
            g = r.get("numeric_guard")
            if g and r.get("change_id"):
                guard_by_change_id[r["change_id"]] = g

    for anchor in interpretations:
        all_anchors.add(anchor)

    for anchor in sorted(all_anchors):
        section_name = SECTION_NAMES.get(anchor, anchor)
        section_year_pairs = [f"{y_old}-{y_new}" for y_old, y_new in year_pairs]

        churn_scores = {}
        for (y_old, y_new), records in records_by_year.items():
            sec_recs = [r for r in records if r.get("anchor") == anchor]
            changed = [r for r in sec_recs if r.get("classification") != "unchanged"]
            matched = [r for r in sec_recs if r.get("classification") not in ("added", "removed")]
            classifications = [r["classification"] for r in matched]
            score = compute_churn_score(
                matched if matched else [{"old_text": "", "new_text": ""}],
                classifications if classifications else ["unchanged"]
            )
            yp_key = f"{y_old}-{y_new}"
            churn_scores[yp_key] = round(score, 4)

        section_interps = interpretations.get(anchor, [])
        for ir in section_interps:
            g = guard_by_change_id.get(ir.get("change_id"))
            if g:
                ir["numeric_guard"] = g
        has_changes = any(
            ir.get("materiality") != "boilerplate"
            for ir in section_interps
        )
        if not has_changes and anchor not in all_anchors:
            continue

        n_material = sum(1 for ir in section_interps if ir.get("materiality") == "material")
        n_notable = sum(1 for ir in section_interps if ir.get("materiality") == "notable")
        n_boilerplate = sum(1 for ir in section_interps if ir.get("materiality") == "boilerplate")
        n_guard = sum(1 for ir in section_interps if ir.get("numeric_guard"))
        churn_vals = [v for v in churn_scores.values() if v is not None]
        latest_churn = churn_scores.get(section_year_pairs[-1]) if section_year_pairs else None
        trend = trends.get(anchor, "")

        sections.append({
            "ticker": ticker,
            "anchor": anchor,
            "section_name": section_name,
            "year_pairs": section_year_pairs,
            "churn_scores": churn_scores,
            "changes": section_interps,
            "trend_narrative": trend,
            "n_material": n_material,
            "n_notable": n_notable,
            "n_boilerplate": n_boilerplate,
            "n_guard": n_guard,
            "n_surfaced": n_material + n_notable,
            "latest_churn": latest_churn,
            "max_churn": max(churn_vals) if churn_vals else 0.0,
            "has_content": (n_material + n_notable + n_boilerplate) > 0 or bool(trend),
        })

    xbrl_report = _build_xbrl_report(xbrl_deltas, year_pairs)

    summary = {
        "material": sum(s["n_material"] for s in sections),
        "notable": sum(s["n_notable"] for s in sections),
        "boilerplate": sum(s["n_boilerplate"] for s in sections),
        "guard": sum(s["n_guard"] for s in sections),
        "surfaced": sum(s["n_surfaced"] for s in sections),
        "sections_total": len(sections),
        "sections_with_content": sum(1 for s in sections if s["has_content"]),
    }

    return {
        "ticker": ticker,
        "entity_name": entity_name or ticker,
        "year_range": year_range,
        "_year_pairs": year_pairs,
        "sections": sections,
        "summary": summary,
        "xbrl_deltas": xbrl_report,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _build_xbrl_report(xbrl_deltas, year_pairs):
    """Build the XBRL portion of the report with helper metadata."""
    if not xbrl_deltas:
        return {}

    year_pairs_str = [f"{y_old}-{y_new}" for y_old, y_new in year_pairs]
    report = {"_year_pairs": year_pairs_str}

    # Order tags: financial statement tags first, then alphabetical
    priority_tags = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "ResearchAndDevelopmentExpense",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
    ]
    all_tags = list(xbrl_deltas.keys())
    ordered = []
    for pt in priority_tags:
        if pt in all_tags:
            ordered.append(pt)
            all_tags.remove(pt)
    ordered.extend(sorted(all_tags))
    report["_tag_order"] = ordered

    for tag, yp_deltas in xbrl_deltas.items():
        report[tag] = yp_deltas

    # Humanized labels + the most-recent absolute value per tag (for display).
    report["_labels"] = {tag: XBRL_LABELS.get(tag, tag) for tag in ordered}
    latest = {}
    for tag in ordered:
        yp_deltas = xbrl_deltas.get(tag, {})
        val, yp_used = None, None
        for yp in year_pairs_str:  # ascending — last hit is most recent
            d = yp_deltas.get(yp)
            if d and d.get("new") is not None:
                val, yp_used = d["new"], yp
        latest[tag] = {"value_str": _fmt_money(val, tag), "yp": yp_used}
    report["_latest"] = latest

    return report


def render_html(report_data, template_dir=None):
    """Render the Delta report as HTML using Jinja2.

    Args:
        report_data: dict from build_report_data()
        template_dir: path to templates dir (default: src/web/templates/)

    Returns HTML string.
    """
    if template_dir is None:
        template_dir = _TEMPLATE_DIR

    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("report.html")
    return template.render(report=report_data)


def render_cli_summary(report_data) -> str:
    """Render the CLI text summary for a report.

    Returns a formatted string for terminal output.
    """
    lines = []
    ticker = report_data["ticker"]
    entity = report_data.get("entity_name", ticker)
    yr_start = report_data["year_range"][0]
    yr_end = report_data["year_range"][-1]

    lines.append(f"\n{'='*70}")
    lines.append(f"  {ticker} ({entity}) — Delta Change Report")
    lines.append(f"  {yr_start} → {yr_end}")
    lines.append(f"{'='*70}")

    # Churn scores
    lines.append(f"\n{'─'*70}")
    lines.append("  Churn Scores")
    lines.append(f"{'─'*70}")
    lines.append(f"  {'Section':<40} | " + " | ".join(
        f"{yp[0]}-{yp[1]}" for yp in report_data["_year_pairs"]
    ))
    lines.append(f"  {'-'*40}-+-" + "-+-".join("-"*9 for _ in report_data["_year_pairs"]))

    for sec in report_data["sections"]:
        row = f"  {sec['section_name']:<40} |"
        for yp in report_data["_year_pairs"]:
            yp_key = f"{yp[0]}-{yp[1]}"
            score = sec["churn_scores"].get(yp_key)
            if score is not None:
                bar = "█" * min(int(score * 20), 20)
                row += f" {score:.2f} {bar:<6}|"
            else:
                row += "    —     |"
        lines.append(row)

    # Material changes summary
    material = []
    notable = []
    boilerplate = []
    for sec in report_data["sections"]:
        for ir in sec["changes"]:
            if ir.get("materiality") == "material":
                material.append((sec["section_name"], ir))
            elif ir.get("materiality") == "notable":
                notable.append((sec["section_name"], ir))
            elif ir.get("materiality") == "boilerplate":
                boilerplate.append((sec["section_name"], ir))

    lines.append(f"\n  Material changes: {len(material)}")
    for section_name, ir in material[:10]:
        lines.append(f"    [{ir.get('change_type', '?')}] {section_name}")
        lines.append(f"      {ir.get('summary', '')}")
        why = ir.get("why_it_matters")
        if why:
            lines.append(f"      Why: {why}")

    if len(material) > 10:
        lines.append(f"    ... and {len(material) - 10} more")

    lines.append(f"\n  Notable: {len(notable)} | Boilerplate: {len(boilerplate)}")

    # Validation status
    unvalidated = []
    for sec in report_data["sections"]:
        for ir in sec["changes"]:
            if ir.get("_unvalidated"):
                unvalidated.append(ir)
    if unvalidated:
        lines.append(f"\n  ⚠ {len(unvalidated)} unvalidated interpretation(s)")

    lines.append(f"\n  Report: {DELTA_REPORTS_DIR}/{ticker}.html")
    lines.append(f"{'='*70}")

    return "\n".join(lines)


def write_report(ticker, html):
    """Write rendered HTML to data/reports/{ticker}.html."""
    os.makedirs(DELTA_REPORTS_DIR, exist_ok=True)
    path = os.path.join(DELTA_REPORTS_DIR, f"{ticker}.html")
    with open(path, "w") as f:
        f.write(html)
    return path


def write_interpretations(interpretations, trends, ticker, year_pairs):
    """Persist interpretations and trends to disk for later re-rendering.
    
    Writes to data/diffs/{ticker}/_interpretations.jsonl and
    data/diffs/{ticker}/_trends.jsonl.
    """
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"
    os.makedirs(output_dir, exist_ok=True)

    interp_path = os.path.join(output_dir, "_interpretations.jsonl")
    with open(interp_path, "w") as f:
        for anchor, interps in sorted(interpretations.items()):
            for ir in interps:
                ir["_anchor"] = anchor
                f.write(json.dumps(ir) + "\n")

    trends_path = os.path.join(output_dir, "_trends.jsonl")
    with open(trends_path, "w") as f:
        for anchor, text in sorted(trends.items()):
            if text:
                f.write(json.dumps({"anchor": anchor, "narrative": text}) + "\n")


def load_interpretations(ticker):
    """Load persisted interpretations and trends from disk.

    Returns (interpretations: {anchor: [records]}, trends: {anchor: text}).
    """
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

    trends = {}
    trends_path = os.path.join(output_dir, "_trends.jsonl")
    if os.path.exists(trends_path):
        with open(trends_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    tr = json.loads(line)
                    trends[tr["anchor"]] = tr["narrative"]

    return interpretations, trends


def build_report_index(tickers, report_dir=None):
    """Build data/reports/index.html listing all ticker reports.

    Args:
        tickers: list of ticker symbols (e.g. ["AAPL", "MSFT", ...])
        report_dir: path to reports dir

    Returns HTML string.
    """
    if report_dir is None:
        report_dir = DELTA_REPORTS_DIR

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    tpl = env.from_string("""{% extends "base.html" %}
{% block title %}FinDocQA Delta — Reports{% endblock %}
{% block content %}
<div class="hero-band">
  <h1 class="display-xl">Delta Reports</h1>
  <p class="body-lg" style="color: var(--color-body); margin-top: var(--space-lg); max-width: 600px; margin-left: auto; margin-right: auto;">
    Filing change-intelligence reports for the Magnificent 7.
  </p>
</div>

<div class="content-band">
  <div style="max-width: 800px; margin: 0 auto;">
    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: var(--space-lg);">
    {% for t in tickers %}
      <a href="{{ t }}.html" class="card-feature" style="text-decoration: none; display: block; color: var(--color-ink);">
        <div style="font-family: var(--font-mono); font-size: var(--text-display-sm); color: var(--color-primary);">{{ t }}</div>
        <div class="body-sm" style="margin-top: var(--space-xs);">{{ names.get(t, t) }}</div>
        <div class="caption" style="margin-top: var(--space-md);">View report &rarr;</div>
      </a>
    {% endfor %}
    </div>
  </div>
</div>
{% endblock %}""")

    names = {
        "AAPL": "Apple Inc.",
        "AMZN": "Amazon.com, Inc.",
        "GOOGL": "Alphabet Inc.",
        "META": "Meta Platforms, Inc.",
        "MSFT": "Microsoft Corporation",
        "NVDA": "NVIDIA Corporation",
        "TSLA": "Tesla, Inc.",
    }

    return tpl.render(tickers=sorted(tickers), names=names)
