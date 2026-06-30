TICKERS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
}

USER_AGENT = "FinDocQA pulkyeet@gmail.com"
SEC_RATE_LIMIT = 8

RAW_DIR = "data/raw"
CHUNKS_DIR = "data/chunks"
CHROMA_DIR = "data/chroma"

CHUNK_SIZE_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 50

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

OPENCODE_AGENT = "chat"

TOP_K_RETRIEVE = 20
