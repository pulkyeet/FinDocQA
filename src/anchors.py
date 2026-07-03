"""Stable anchor vocabulary and derivation rules for section-aware chunks.

Anchors are the shared label space used for gold_chunk labels across all chunking
strategies. They are intentionally independent of chunk_id so that the same eval
key works for fixed-size, section-aware, and any future strategy.
"""

import re
from typing import Optional

ANCHOR_VOCABULARY = {
    # Item-level prose anchors
    "item1_business",
    "item1a_risk",
    "item1b_unresolved",
    "item1c_cybersecurity",
    "item2_properties",
    "item3_legal",
    "item4_safety",
    "item6_reserved",
    "item7_mdna",
    "item7a_market_risk",
    "item8_financials",
    "item5_market",
    "item9_changes",
    "item9a_controls",
    "item9b_other",
    "item9c_foreign",
    "item10_governance",
    "item11_compensation",
    "item12_equity",
    "item13_relationships",
    "item14_accountant",
    "item15_exhibits",
    "item16_summary",
    # Financial-statement table anchors
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "stockholders_equity",
    "notes_to_financials",
    # Fallback anchors for headers that match an item number but no descriptive keywords.
    "item_unknown",
    "item1_unknown","item1a_unknown","item1b_unknown","item1c_unknown",
    "item2_unknown","item3_unknown","item4_unknown","item5_unknown","item6_unknown",
    "item7_unknown","item7a_unknown","item8_unknown",
    "item9_unknown","item9a_unknown","item9b_other","item9b_unknown","item9c_unknown",
    "item10_unknown","item11_unknown","item12_unknown","item13_unknown",
    "item14_unknown","item15_unknown","item16_unknown",
}


# Mapping from normalized item-header text to prose anchor.
# Order matters: longer, more specific headers are checked first.
ITEM_HEADER_PATTERNS = [
    ("item1c_cybersecurity", ["item 1c", "cybersecurity"]),
    ("item1b_unresolved", ["item 1b", "unresolved"]),
    ("item1a_risk", ["item 1a", "risk"]),
    ("item1_business", ["item 1", "business"]),
    ("item2_properties", ["item 2", "properties"]),
    ("item3_legal", ["item 3", "legal"]),
    ("item4_safety", ["item 4", "safety"]),
    ("item5_market", ["item 5", "market"]),
    ("item6_reserved", ["item 6", "reserved"]),
    ("item7a_market_risk", ["item 7a", "quantitative"]),
    ("item7_mdna", ["item 7", "management"]),
    ("item8_financials", ["item 8", "financial"]),
    ("item9a_controls", ["item 9a", "controls"]),
    ("item9b_other", ["item 9b", "other"]),
    ("item9c_foreign", ["item 9c", "foreign"]),
    ("item9_changes", ["item 9", "disagreements"]),
    ("item10_governance", ["item 10", "directors"]),
    ("item11_compensation", ["item 11", "compensation"]),
    ("item12_equity", ["item 12", "security"]),
    ("item13_relationships", ["item 13", "relationships"]),
    ("item14_accountant", ["item 14", "accountant"]),
    ("item15_exhibits", ["item 15", "exhibit"]),
    ("item16_summary", ["item 16", "summary"]),
]

ITEM_NUM_RE = re.compile(r"\bitem\s+(\d+)([a-z]?)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation."""
    text = " ".join(text.split())
    return text.lower().strip(".:")


def item_header_to_anchor(header_text: str) -> str:
    """Map an Item header like 'Item 7. Management's Discussion...' to a stable anchor.

    Robust to SEC HTML text fragmentation (e.g. MSFT splits 'FINANCIAL STATEMENTS'
    across spans) by extracting the item number via a word-bounded regex and
    requiring only a single distinctive keyword after the number.
    """
    norm = _normalize(header_text)
    m = ITEM_NUM_RE.search(norm)
    if not m:
        return "unknown"
    num = m.group(1) + m.group(2)
    for anchor, keywords in ITEM_HEADER_PATTERNS:
        m2 = re.search(r"(\d+[a-z]?)\b", keywords[0])
        if not m2 or m2.group(1).lower() != num.lower():
            continue
        if all(kw in norm for kw in keywords[1:]):
            return anchor
    return f"item{num}_unknown"


def table_heading_to_anchor(heading_text: str, fallback_anchor: str) -> str:
    """Classify a table based on its caption/preceding text.

    Args:
        heading_text: Caption, title, or preceding sentence(s) describing the table.
        fallback_anchor: Anchor of the enclosing Item section if no keyword matches.
    """
    norm = _normalize(heading_text)
    if any(kw in norm for kw in ("statement of operations", "income statement", "consolidated statements of operations")):
        return "income_statement"
    if "operations" in norm and "income" in norm:
        return "income_statement"
    if "balance sheet" in norm or ("assets" in norm and "liabilities" in norm and "equity" in norm):
        return "balance_sheet"
    if any(kw in norm for kw in ("cash flow", "statement of cash flows")):
        return "cash_flow"
    if any(kw in norm for kw in ("stockholders' equity", "shareholders' equity", "stockholders equity", "shareholders equity")):
        return "stockholders_equity"
    if any(kw in norm for kw in ("notes to", "note ", "notes —", "notes-")) and ("financial" in norm or "consolidated" in norm):
        return "notes_to_financials"
    return fallback_anchor


# Common us-gaap XBRL tags mapped to the anchor of the statement/table where they live.
XBRL_TAG_TO_ANCHOR = {
    # Income statement
    "ResearchAndDevelopmentExpense": "income_statement",
    "Revenues": "income_statement",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "income_statement",
    "CostOfGoodsAndServicesSold": "income_statement",
    "GrossProfit": "income_statement",
    "OperatingIncomeLoss": "income_statement",
    "NetIncomeLoss": "income_statement",
    "EarningsPerShareBasic": "income_statement",
    "EarningsPerShareDiluted": "income_statement",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes": "income_statement",
    "IncomeTaxExpenseBenefit": "income_statement",
    "SellingGeneralAndAdministrativeExpense": "income_statement",
    # Balance sheet
    "Assets": "balance_sheet",
    "Liabilities": "balance_sheet",
    "StockholdersEquity": "balance_sheet",
    "CashAndCashEquivalentsAtCarryingValue": "balance_sheet",
    "AccountsReceivableNet": "balance_sheet",
    "InventoryNet": "balance_sheet",
    "PropertyPlantAndEquipmentNet": "balance_sheet",
    "LongTermDebtNoncurrent": "balance_sheet",
    # Cash flow
    "NetCashProvidedByUsedInOperatingActivities": "cash_flow",
    "NetCashProvidedByUsedInInvestingActivities": "cash_flow",
    "NetCashProvidedByUsedInFinancingActivities": "cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "cash_flow",
    "RepurchaseOfCommonStock": "cash_flow",
    "PaymentsOfDividends": "cash_flow",
    "PaymentsOfDividendsCommonStock": "cash_flow",
}
