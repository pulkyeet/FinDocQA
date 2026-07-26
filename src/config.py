import os

from dotenv import load_dotenv

load_dotenv()

TICKERS = {
    "AAPL": "0000320193",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
}

# SEC submissions returns the most-recent 10-K first. NVDA's latest filing is
# FY2026 (period_end 2026-01-25); this project targets FY2025, so fetch the
# prior 10-K for NVDA. See FinDocQA_PLAN.md section 1 (fiscal-year caveat).
TICKER_10K_OFFSET = {
    "NVDA": 1,
}

USER_AGENT = os.environ.get("SEC_USER_AGENT") or "FinDocQA contact@findocqa.dev"
SEC_RATE_LIMIT = 8

RAW_DIR = "data/raw"
CHUNKS_DIR = "data/chunks"
CHROMA_DIR = "data/chroma"
EVAL_DIR = "data/eval"

CHUNK_SIZE_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 50

# 8-config matrix axes (generation model is frozen in .opencode/opencode.json)
CHUNK_STRATEGIES = ["fixedsize", "sectionaware"]

EMBEDDING_MODELS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "e5-small": "intfloat/e5-small-v2",
}

RERANKER_MODEL = "BAAI/bge-reranker-base"
RERANK_TOP_K = 5

OPENCODE_AGENT = "paid-chatter"
OPENCODE_ATTACH = os.environ.get("OPENCODE_ATTACH")  # e.g. "http://localhost:4096"
FAITHFULNESS_JUDGE = os.environ.get("FAITHFULNESS_JUDGE", "").lower() in ("1", "true", "yes")

# OpenRouter API (v2 Delta LLM — preferred over opencode subprocess)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

TOP_K_RETRIEVE = 20
TOP_K_FINAL = 5

# ── v2 Delta constants ──────────────────────────────────────────────────

DELTA_YEARS_DEFAULT = 5
DELTA_YEARS_MAX = 5
DELTA_DIFFS_DIR = "data/diffs"
DELTA_REPORTS_DIR = "data/reports"

# Diff classification thresholds (tuned on 47-pair labeled sample)
# Held-out (10 pairs): precision=0.300, recall=1.000, F1=0.462
DIFF_THRESHOLD_UNCHANGED = 0.95
DIFF_THRESHOLD_MINOR = 0.81
DIFF_THRESHOLD_MAJOR = 0.60

# Numeric guard (fixes numeric-blindness: cosine ~0.99 for pure-number changes).
# Fires only on records cosine calls 'unchanged' — orthogonal to the tuned
# thresholds above, so no re-tuning risk.
NUMERIC_GUARD_PCT = 0.20        # relative YoY move that counts as material
NUMERIC_GUARD_MIN_VALUE = 1.0   # ignore sub-unit numeric noise
NUMERIC_GUARD_MAJOR_PCT = 1.00  # moves >= 100% upgrade to modified_major
# Sections with audited XBRL backing (for XBRL corroboration guard)
FINANCIAL_ANCHORS = ("income_statement", "balance_sheet", "cash_flow")

# Paragraph alignment
ALIGN_SIMILARITY_FLOOR = 0.50  # below this, paragraphs are unmatched

# Chunk size fix (v2) — embedding models cap at 512 tokens
SA_TARGET_TOKENS = 350   # was 600
SA_MAX_TOKENS = 500      # was 800
SA_MIN_TOKENS = 100      # unchanged

# XBRL tags for delta join (financially-loaded sections)
XBRL_DELTA_TAGS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "ResearchAndDevelopmentExpense", "CostOfGoodsAndServicesSold",
    "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
    "IncomeTaxExpenseBenefit",
    "SellingGeneralAndAdministrativeExpense",
    "EarningsPerShareBasic", "EarningsPerShareDiluted",
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForRepurchaseOfCommonStock", "PaymentsOfDividends",
    "Assets", "Liabilities", "StockholdersEquity",
    "LongTermDebtNoncurrent", "CashAndCashEquivalentsAtCarryingValue",
    "AccountsReceivableNetCurrent", "InventoryNet",
    "PropertyPlantAndEquipmentNet",
]

# ── Report composition (v2 narrative report) ────────────────────────────
#
# The report is an essay, not a diff dump: each chapter is one LLM-composed
# narrative built from the material/notable interpretations of its anchors.
# Anchors absent from every chapter are deliberately dropped from the report —
# they carry almost no surfaced change (Properties, Exhibits, Compensation).
REPORT_CHAPTERS = [
    {
        "id": "business",
        "title": "The Business",
        "subtitle": "Strategy, segments, and geographic footprint",
        "anchors": ["item1_business", "item5_market"],
    },
    {
        "id": "risk",
        "title": "Risk Landscape",
        "subtitle": "What management newly fears, and what it stopped fearing",
        "anchors": ["item1a_risk", "item7a_market_risk", "item1c_cybersecurity"],
    },
    {
        "id": "mdna",
        "title": "Management's Discussion",
        "subtitle": "How management explains its own numbers",
        "anchors": ["item7_mdna"],
    },
    {
        "id": "legal",
        "title": "Legal & Regulatory",
        "subtitle": "Proceedings, settlements, and regulatory exposure",
        "anchors": ["item3_legal", "item9b_other"],
    },
]

# Anchors whose *material* changes are folded into the Financial Performance
# chapter as accounting-policy / restatement notes. Variant B sets this empty.
FINANCIALS_NARRATIVE_ANCHORS = ["item8_financials", "income_statement",
                                "cash_flow", "balance_sheet"]

# XBRL statement tables: (group title, [tags in display order]).
XBRL_STATEMENT_GROUPS = [
    ("Income Statement", [
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
        "CostOfGoodsAndServicesSold", "GrossProfit",
        "ResearchAndDevelopmentExpense", "SellingGeneralAndAdministrativeExpense",
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        "IncomeTaxExpenseBenefit", "NetIncomeLoss",
        "EarningsPerShareBasic", "EarningsPerShareDiluted",
    ]),
    ("Cash Flow", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForRepurchaseOfCommonStock", "PaymentsOfDividends",
    ]),
    ("Balance Sheet", [
        "Assets", "Liabilities", "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "AccountsReceivableNetCurrent", "InventoryNet",
        "PropertyPlantAndEquipmentNet", "LongTermDebtNoncurrent",
    ]),
]

# Churn over a handful of paragraphs is meaningless — a stub section where the
# anchor matched a header but almost no body text scores 1.00 and crowds the
# real signal out of the churn table.
CHURN_MIN_RECORDS = 8

# Narrative composition
NARRATIVE_MIN_WORDS = 600
NARRATIVE_MAX_WORDS = 900
NARRATIVE_MAX_EVIDENCE = 40   # interpretations fed to one chapter call
WORDS_PER_MINUTE = 220        # for the read-time estimate


def sanitize_prompt(text: str) -> str:
    """Strip ASCII control characters (except tab/newline/return) from prompt text."""
    return "".join(c for c in text if c == "\t" or c == "\n" or c == "\r" or c >= " ")
