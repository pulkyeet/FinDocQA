"""Create chunks from 10-K HTML filings.

Two strategies are supported:
- fixed-size: sliding token windows snapped to paragraph boundaries (baseline).
- sectionaware: Item-header boundaries, atomic tables, and section anchors.

Run from the repo root with `cd src` so relative paths resolve to `src/data/`.
"""

import argparse
import json
import os
import re
import warnings
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
from config import RAW_DIR, CHUNKS_DIR, TICKERS, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS
from anchors import item_header_to_anchor, table_heading_to_anchor

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

CHARS_PER_TOKEN = 4
CHUNK_SIZE_CHARS = CHUNK_SIZE_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN

# Section-aware sizing (plan §5: target 512-800 tokens; small-section floor ~100 tokens)
SA_TARGET_TOKENS = 600
SA_MAX_TOKENS = 800
SA_MIN_TOKENS = 100
SA_TARGET_CHARS = SA_TARGET_TOKENS * CHARS_PER_TOKEN
SA_MAX_CHARS = SA_MAX_TOKENS * CHARS_PER_TOKEN
SA_MIN_CHARS = SA_MIN_TOKENS * CHARS_PER_TOKEN

ITEM_HEADER_RE = re.compile(r"^Item\s+\d+[A-Z]?\b", re.IGNORECASE)
SCALE_RE = re.compile(
    r"\(?\s*in\s+(millions|thousands|billions)",
    re.IGNORECASE,
)


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


# ---------------------------------------------------------------------------
# Section-aware helpers
# ---------------------------------------------------------------------------


def _is_item_header(line: str) -> bool:
    """Return True for real Item headers like 'Item 1.    Business'.

    TOC entries such as 'Item 1.' on their own line are excluded by requiring
    alphabetic content after the item number.
    """
    line = line.strip()
    if not ITEM_HEADER_RE.match(line):
        return False
    rest = ITEM_HEADER_RE.sub("", line).strip()
    rest = re.sub(r"^[.:\s]+", "", rest)
    return len(rest) > 3 and any(c.isalpha() for c in rest)


def _table_to_text(table) -> str:
    """Convert a <table> to a readable row-per-line text representation."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [
            " ".join(td.get_text(" ", strip=True).split())
            for td in tr.find_all(["td", "th"])
        ]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _find_table_caption(table):
    """Return caption/scale/heading text immediately preceding the table in the DOM.

    Financial-statement tables in inline-XBRL usually have their title and
    "in millions" scale line in preceding sibling <div> elements, not inside
    the <table> itself.
    """

    def _looks_like_noise(text: str) -> bool:
        # XBRL metadata / context IDs (e.g., "aapl-20250927") are noise.
        if re.fullmatch(r"[a-z0-9\-]+", text) and len(text) < 40:
            return True
        return False

    captions = []
    # Search previous siblings of the table itself and its immediate parent.
    nodes = [table]
    if table.parent is not None:
        nodes.append(table.parent)

    for node in nodes:
        prev = node.previous_sibling
        collected = []
        for _ in range(4):
            if prev is None:
                break
            if getattr(prev, "name", None):
                t = prev.get_text(strip=True)
                if t and not _looks_like_noise(t) and len(t) <= 300:
                    collected.append(t)
            prev = prev.previous_sibling
        captions = list(reversed(collected)) + captions
    return captions


def _extract_segments(soup):
    """Walk the DOM in document order and return prose/table segments.

    Tables are captured as atomic segments so they are never split mid-table.
    Any caption/heading/scale line found in preceding siblings is prepended to
    the table text so the table can be classified correctly.
    """
    segments = []
    current_lines = []

    def flush_text():
        if current_lines:
            text = "\n".join(current_lines)
            segments.append({"kind": "prose", "text": text})
            current_lines.clear()

    def walk(node):
        if node.name in ("script", "style", "head"):
            return
        if node.name == "table":
            flush_text()
            t = _table_to_text(node)
            if t:
                captions = _find_table_caption(node)
                if captions:
                    t = "\n".join(captions) + "\n" + t
                segments.append({"kind": "table", "text": t, "elem": node})
            return
        if isinstance(node, str):
            txt = " ".join(node.split())
            if txt:
                current_lines.append(txt)
            return
        for child in node.children:
            walk(child)

    walk(soup)
    flush_text()
    return segments


def _split_prose_at_items(segments):
    """Split prose segments at Item headers and tag every segment with its Item."""
    result = []
    current_item = None

    for seg in segments:
        if seg["kind"] == "table":
            seg["item"] = current_item
            result.append(seg)
            continue

        lines = seg["text"].split("\n")
        buf = []
        for line in lines:
            line_stripped = line.strip()
            if _is_item_header(line_stripped):
                if buf:
                    result.append(
                        {"kind": "prose", "text": "\n".join(buf), "item": current_item}
                    )
                    buf = []
                current_item = line_stripped
                buf.append(line)
            else:
                buf.append(line)
        if buf:
            result.append(
                {"kind": "prose", "text": "\n".join(buf), "item": current_item}
            )

    return result


def _split_prose_text(text: str, max_chars: int, target_chars: int) -> list:
    """Split prose at paragraph boundaries, then line boundaries if needed."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

    for p in paragraphs:
        p_len = len(p)
        # If adding this paragraph would exceed the cap and we already have content,
        # flush first. Then add paragraph (even if it alone exceeds cap).
        if current_len and current_len + 2 + p_len > max_chars:
            flush()
        current.append(p)
        current_len += (2 + p_len) if current_len else p_len
        # If we've passed the target, flush to keep chunks near target size.
        if current_len >= target_chars:
            flush()

    flush()

    # Any chunk still over max_chars gets split on single newlines.
    final = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
            continue
        # Split on lines.
        lines = chunk.split("\n")
        buf = []
        buf_len = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if buf_len and buf_len + 1 + len(line) > max_chars:
                final.append("\n".join(buf))
                buf = [line]
                buf_len = len(line)
            else:
                buf.append(line)
                buf_len += (1 + len(line)) if buf_len else len(line)
        if buf:
            final.append("\n".join(buf))
    return final


def _merge_small_prose_chunks(chunks: list, min_chars: int) -> list:
    """Backward-merge prose chunks below min_chars into adjacent prose chunks.

    Tables stay atomic.
    """
    merged = []
    for chunk in chunks:
        if chunk["type"] == "prose" and len(chunk["text"]) < min_chars:
            if merged and merged[-1]["type"] == "prose":
                merged[-1]["text"] += "\n\n" + chunk["text"]
                continue
        merged.append(chunk)
    return merged


def _find_table_scale(preceding_text: str) -> float:
    """Parse the nearest preceding 'in millions/thousands/billions' scale line."""
    lines = [l.strip() for l in reversed(preceding_text.split("\n"))]
    for line in lines:
        m = SCALE_RE.search(line)
        if m:
            word = m.group(1).lower()
            if word.startswith("billion"):
                return 1e9
            if word.startswith("million"):
                return 1e6
            if word.startswith("thousand"):
                return 1e3
    return None


def _build_table_context(item_header: str, preceding_text: str, table_text: str) -> str:
    """Compose context prefix for an atomic table chunk.

    Avoids duplicating a scale line or caption that is already part of the
    atomic table text (e.g., captured from preceding DOM siblings).
    """
    table_norm = " ".join(table_text.split()).lower()

    def _already_present(line: str) -> bool:
        return " ".join(line.split()).lower() in table_norm

    parts = []
    if item_header:
        parts.append(item_header)

    # Scale line (nearest preceding)
    lines = [l.strip() for l in reversed(preceding_text.split("\n"))]
    scale_line = None
    for line in lines:
        if SCALE_RE.search(line):
            scale_line = line
            break
    if scale_line and not _already_present(scale_line):
        parts.append(scale_line)

    # Introducing sentence/caption: nearest preceding non-empty, non-scale, non-item line.
    intro = None
    for line in lines:
        if not line:
            continue
        if SCALE_RE.search(line):
            continue
        if _is_item_header(line):
            continue
        if len(line) > 300:
            line = line[:300] + "..."
        intro = line
        break
    if intro and not _already_present(intro):
        parts.append(intro)

    return "\n".join(parts)


def _derive_table_anchor(table_text: str, item_header: str, item_anchor: str) -> str:
    """Classify a table using its own text, caption, and enclosing section anchor."""
    heading = table_text[:500]
    if item_header:
        heading = item_header + "\n" + heading
    return table_heading_to_anchor(heading, item_anchor)


def chunk_sectionaware(html_path: str, ticker: str, period_end: str) -> list:
    """Create section-aware chunks: Item boundaries, atomic tables, stable anchors."""
    with open(html_path) as f:
        soup = BeautifulSoup(f.read(), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    segments = _extract_segments(soup)
    itemized = _split_prose_at_items(segments)

    chunks = []
    current_item = None
    current_item_anchor = "item1_business"
    prose_buffer = []
    recent_prose_text = []

    def flush_prose():
        nonlocal prose_buffer
        if not prose_buffer:
            return
        text = "\n".join(prose_buffer)
        recent_prose_text.append(text)
        # Keep a rolling window for table context (~3000 chars).
        context_text = "\n".join(recent_prose_text)
        if len(context_text) > 3000:
            recent_prose_text[:] = [context_text[-3000:]]

        sub_chunks = _split_prose_text(text, SA_MAX_CHARS, SA_TARGET_CHARS)
        for sub in sub_chunks:
            chunks.append(
                {
                    "anchor": current_item_anchor,
                    "item": current_item,
                    "type": "prose",
                    "table_scale": None,
                    "text": sub,
                }
            )
        prose_buffer = []

    for seg in itemized:
        item = seg.get("item")
        if item != current_item:
            flush_prose()
            current_item = item
            current_item_anchor = item_header_to_anchor(item) if item else "item1_business"
            recent_prose_text = []

        if seg["kind"] == "table":
            flush_prose()
            preceding = "\n".join(recent_prose_text)
            table_anchor = _derive_table_anchor(
                seg["text"], current_item, current_item_anchor
            )
            scale = _find_table_scale(preceding)
            context = _build_table_context(current_item, preceding, seg["text"])
            full_text = context + "\n" + seg["text"] if context else seg["text"]
            chunks.append(
                {
                    "anchor": table_anchor,
                    "item": current_item,
                    "type": "table",
                    "table_scale": scale,
                    "text": full_text,
                }
            )
        else:
            prose_buffer.extend(seg["text"].split("\n"))

    flush_prose()

    chunks = _merge_small_prose_chunks(chunks, SA_MIN_CHARS)

    # Assign char_span, chunk_id, and page in the canonical reconstructed text.
    canonical = ""
    for idx, chunk in enumerate(chunks):
        start = len(canonical)
        canonical += chunk["text"]
        end = len(canonical)
        chunk["char_span"] = [start, end]
        chunk["chunk_id"] = (
            f"{ticker.lower()}-10k-{period_end}-sectionaware-{idx:04d}"
        )
        chunk["page"] = None

    return chunks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _write_chunks(path: str, chunks: list):
    with open(path, "w") as f:
        json.dump(chunks, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Chunk 10-K HTML filings.")
    parser.add_argument(
        "--strategy",
        choices=["fixedsize", "sectionaware", "both"],
        default="both",
        help="Chunking strategy to run (default: both).",
    )
    args = parser.parse_args()

    os.makedirs(CHUNKS_DIR, exist_ok=True)

    for ticker in TICKERS:
        html_path = f"{RAW_DIR}/{ticker}_10k.html"
        meta_path = f"{RAW_DIR}/{ticker}_10k_meta.json"
        if not os.path.exists(html_path):
            print(f"[skip] {ticker}: run fetch.py first")
            continue
        with open(meta_path) as f:
            period_end = json.load(f)["period_end"]

        if args.strategy in ("fixedsize", "both"):
            text = html_to_text(html_path)
            chunks = chunk_text(text, ticker, period_end)
            out_path = f"{CHUNKS_DIR}/{ticker}_fixedsize.json"
            _write_chunks(out_path, chunks)
            print(f"[fixedsize] {ticker}: {len(chunks)} chunks -> {out_path}")

        if args.strategy in ("sectionaware", "both"):
            chunks = chunk_sectionaware(html_path, ticker, period_end)
            out_path = f"{CHUNKS_DIR}/{ticker}_sectionaware.json"
            _write_chunks(out_path, chunks)
            print(f"[sectionaware] {ticker}: {len(chunks)} chunks -> {out_path}")


if __name__ == "__main__":
    main()
