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

USER_AGENT = "FinDocQA pulkyeet@gmail.com"
SEC_RATE_LIMIT = 8

RAW_DIR = "data/raw"
CHUNKS_DIR = "data/chunks"
CHROMA_DIR = "data/chroma"
EVAL_DIR = "data/eval"

CHUNK_SIZE_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 50

# 8-config matrix axes (generation model is frozen in .opencode/agent/chat.md)
CHUNK_STRATEGIES = ["fixedsize", "sectionaware"]

EMBEDDING_MODELS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "e5-small": "intfloat/e5-small-v2",
}

# Legacy single-model alias used by W1 scripts until the matrix refactor lands.
EMBEDDING_MODEL = EMBEDDING_MODELS["bge-small"]

RERANKER_MODEL = "BAAI/bge-reranker-base"
RERANK_TOP_K = 5

OPENCODE_AGENT = "chat"

TOP_K_RETRIEVE = 20
TOP_K_FINAL = 5
