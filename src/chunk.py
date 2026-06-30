"""Create chunks from fixed-size token windows which prioritize paragraph boundaries."""

import json
import os
import re
from bs4 import BeautifulSoup
from config import RAW_DIR, CHUNKS_DIR, TICKERS, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS

CHARS_PER_TOKEN = 4
CHUNK_SIZE_CHARS = CHUNK_SIZE_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN


def html_to_text(html_path):
    with open(html_path) as f:
        soup = BeautifulSoup(f.read(), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def snap_to_paragraph(text, target_pos, window=300):
    # we look for the nearest \n\n within 'window' characters of the target_pos
    lo, hi = max(0, target_pos - window), min(len(text), target_pos + window)
    search_zone = text[lo:hi]
    candidates = [m.start() + lo for m in re.finditer(r"\n\n", search_zone)]
    if not candidates:
        return target_pos
    return min(candidates, key=lambda p: abs(p - target_pos))


def chunk_text(text, ticker, period_end):
    chunks = []
    pos = 0
    idx = 0
    n = len(text)
    while pos < n:
        target_end = pos + CHUNK_SIZE_TOKENS
        end = snap_to_paragraph(text, target_end) if target_end < n else n
        if end <= pos:
            end = min(pos + CHUNK_SIZE_CHARS, n)
        chunk_str = text[pos:end].strip()
        if chunk_str:
            chunks.append(
                {
                    "chunk_id": f"{ticker.lower()}-10k-{period_end}-fixedsize-{idx:04d}",
                    "anchor": None,
                    "type": "prose",
                    "table_scale": None,
                    "char_span": [pos, end],
                    "text": chunk_str,
                }
            )
            idx += 1
        pos = max(end - OVERLAP_CHARS, pos + 1)
    return chunks


if __name__ == "__main__":
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    for ticker in TICKERS:
        html_path = f"{RAW_DIR}/{ticker}_10k.html"
        meta_path = f"{RAW_DIR}/{ticker}_10k_meta.json"
        if not os.path.exists(html_path):
            print(f"[skip] {ticker}: run fetch.py first")
            continue
        with open(meta_path) as f:
            period_end = json.load(f)["period_end"]

        text = html_to_text(html_path)
        chunks = chunk_text(text, ticker, period_end)

        out_path = f"{CHUNKS_DIR}/{ticker}_fixedsize.json"
        with open(out_path, "w") as f:
            json.dump(chunks, f, indent=2)
        print(f"[chunked] {ticker}: {len(chunks)} chunks -> {out_path}")
