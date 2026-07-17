"""Generate numerical eval questions from XBRL companyfacts.

For each (ticker, tag) where the FY annual value exists in the filing we
ingested, create a numerical eval question. gold_chunks = the anchor from
XBRL_TAG_TO_ANCHOR. gold_span = a char range in the original raw text covering
the financial-statement table (found by searching for the statement heading).
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anchors import XBRL_TAG_TO_ANCHOR
from chunk import html_to_text
from config import RAW_DIR, TICKERS

# Curated tags present across the Magnificent 7 FY2025 filings.
# 3 per ticker (21 total) ensures every ticker has at least one numerical
# question; we cap to 20, so the 7th ticker gets 2. Assets and OCF are
# valuable but would push the distribution to 4-5 per ticker for early
# tickers and 0 for later ones.
NUMERICAL_TAGS = [
    "ResearchAndDevelopmentExpense",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
]

REVENUE_FALLBACKS = ["Revenues"]

STATEMENT_HEADINGS = {
    "income_statement": [
        "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "CONSOLIDATED STATEMENT OF OPERATIONS",
        "CONSOLIDATED STATEMENTS OF INCOME",
        "CONSOLIDATED STATEMENT OF INCOME",
        "CONSOLIDATED STATEMENTS OF EARNINGS",
    ],
    "balance_sheet": [
        "CONSOLIDATED BALANCE SHEETS",
        "CONSOLIDATED BALANCE SHEET",
    ],
    "cash_flow": [
        "CONSOLIDATED STATEMENTS OF CASH FLOWS",
        "CONSOLIDATED STATEMENT OF CASH FLOWS",
    ],
}

GOLD_SPAN_CHARS = 4000

READABLE = {
    "ResearchAndDevelopmentExpense": "research and development expense",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "total revenue",
    "Revenues": "total revenue",
    "NetIncomeLoss": "net income",
    "Assets": "total assets",
    "NetCashProvidedByUsedInOperatingActivities": "net cash provided by operating activities",
}


def _find_fy_value(companyfacts, period_end, tag):
    try:
        entries = companyfacts["facts"]["us-gaap"][tag]["units"]["USD"]
    except KeyError:
        return None
    for e in entries:
        if (
            e.get("form") == "10-K"
            and e.get("fp") == "FY"
            and e.get("end") == period_end
            and "start" in e
        ):
            return e["val"], e["start"], e["end"]
    return None


def _format_value_text(val):
    if abs(val) >= 1e9:
        return f"${val / 1e9:.1f} billion"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.0f} million"
    return f"${val}"


def _find_gold_span(html_path, anchor):
    raw = html_to_text(html_path)
    for h in STATEMENT_HEADINGS.get(anchor, []):
        m = re.search(re.escape(h), raw, re.IGNORECASE)
        if m:
            start = m.start()
            end = min(start + GOLD_SPAN_CHARS, len(raw))
            return [start, end]
    return None


def _resolve_revenue(companyfacts, period_end):
    for tag in ["RevenueFromContractWithCustomerExcludingAssessedTax"] + REVENUE_FALLBACKS:
        res = _find_fy_value(companyfacts, period_end, tag)
        if res:
            return tag, res
    return None, None


def generate_numerical():
    questions = []
    qid = 0
    for ticker in TICKERS:
        with open(f"{RAW_DIR}/{ticker}_10k_meta.json") as f:
            meta = json.load(f)
        period_end = meta["period_end"]
        with open(f"{RAW_DIR}/{ticker}_companyfacts.json") as f:
            cf = json.load(f)
        html_path = f"{RAW_DIR}/{ticker}_10k.html"
        for tag in NUMERICAL_TAGS:
            if tag in (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
            ):
                rtag, res = _resolve_revenue(cf, period_end)
                if not res:
                    continue
                tag = rtag
            else:
                res = _find_fy_value(cf, period_end, tag)
            if not res:
                continue
            val, start, end = res
            anchor = XBRL_TAG_TO_ANCHOR.get(tag)
            if not anchor:
                continue
            qid += 1
            gold_span = _find_gold_span(html_path, anchor)
            q = {
                "id": f"{ticker.lower()}-fy{end[:4]}-{tag[:24].lower()}-{qid:03d}",
                "question": f"What was {ticker}'s {READABLE.get(tag, tag)} in FY{end[:4]}?",
                "type": "numerical",
                "expected_route": "corpus",
                "gold_chunks": [anchor],
                "gold_spans": [gold_span] if gold_span else [],
                "answer": {
                    "value": val,
                    "unit": "USD",
                    "text": _format_value_text(val),
                },
                "source": f"xbrl:us-gaap:{tag}",
                "period_end": end,
            }
            questions.append(q)
    if len(questions) > 20:
        questions = questions[:20]
    return questions


if __name__ == "__main__":
    qs = generate_numerical()
    os.makedirs("data/eval", exist_ok=True)
    out = "data/eval/questions_numerical.jsonl"
    with open(out, "w") as f:
        for q in qs:
            f.write(json.dumps(q) + "\n")
    print(f"Wrote {len(qs)} numerical questions to {out}")
    for q in qs:
        print(
            f"  {q['id']}: anchor={q['gold_chunks']} ans={q['answer']['text']} span={'yes' if q['gold_spans'] else 'no'}"
        )
