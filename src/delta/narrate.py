"""Stage 8: narrative composition — turn interpreted diffs into a readable report.

The pipeline up to stage 7 produces several hundred verified change records per
ticker. Rendering those directly is a diff dump, not a report. This stage
composes them into chapter-length analyst prose: one LLM call per chapter, fed
only the material/notable interpretations for that chapter's anchors, with
every substantive claim carrying a citation back to a specific change record.

Traceability survives the prose. The narrator cites short labels (E1, E2, ...)
rather than raw change_ids — shorter to emit and far less error-prone — and any
label it invents that isn't in the evidence pool is dropped, mirroring the
verbatim-quote validation in interpret.py.
"""

import html
import re

from config import (
    NARRATIVE_MIN_WORDS, NARRATIVE_MAX_WORDS, NARRATIVE_MAX_EVIDENCE,
)
from anchors import SECTION_NAMES
from delta.interpret import call_llm, SYSTEM_PROSE
from delta.prompts import CHAPTER_NARRATIVE_PROMPT, EXEC_SUMMARY_PROMPT

CITE_RE = re.compile(r"\[E(\d+)\]")

# Prose is far more token-hungry than the stage-7 JSON records.
NARRATIVE_MAX_TOKENS = 8192


def _drop_dangling_sentence(text: str) -> str:
    """Trim a trailing fragment left by a length-capped response.

    A cut-off generation ends mid-sentence ("...program saw minimal initial
    utilization. The"). Rendering that reads as a bug in the report, so the
    fragment is dropped back to the last complete sentence.
    """
    truncated = text.endswith("[TRUNCATED]")
    text = text.replace("[TRUNCATED]", "").strip()
    if not truncated:
        return text
    # Keep everything up to the final sentence-ending punctuation.
    m = None
    for m in re.finditer(r'[.!?]["”\')\]]?(?=\s|$)', text):
        pass
    return text[:m.end()].strip() if m else text

# Materiality ordering — material evidence is fed to the narrator first, so a
# chapter with more than NARRATIVE_MAX_EVIDENCE candidates keeps the good ones.
_MATERIALITY_RANK = {"material": 0, "notable": 1}


def build_evidence_pool(interpretations: dict, anchors: list,
                        max_items: int = NARRATIVE_MAX_EVIDENCE) -> list[dict]:
    """Collect citable evidence for one chapter from the interpretation store.

    Args:
        interpretations: {anchor: [interpretation_records]}
        anchors: anchor names belonging to this chapter
        max_items: cap on evidence fed to a single LLM call

    Returns a list of evidence dicts labelled E1..EN, material first then
    chronological. Boilerplate and unvalidated records are excluded — an
    unvalidated record has no trustworthy quote, so it cannot back a claim.
    """
    pool = []
    for anchor in anchors:
        for ir in interpretations.get(anchor, []):
            if ir.get("_unvalidated"):
                continue
            if ir.get("materiality") not in ("material", "notable"):
                continue
            pool.append({
                "change_id": ir.get("change_id", ""),
                "anchor": anchor,
                "section_name": SECTION_NAMES.get(anchor, anchor),
                "y_old": ir.get("_y_old", ""),
                "y_new": ir.get("_y_new", ""),
                "materiality": ir.get("materiality", ""),
                "change_type": ir.get("change_type", ""),
                "summary": ir.get("summary", ""),
                "why_it_matters": ir.get("why_it_matters") or "",
                "old_quote": ir.get("old_quote", ""),
                "new_quote": ir.get("new_quote", ""),
                "numeric_guard": ir.get("numeric_guard"),
            })

    pool.sort(key=lambda e: (
        _MATERIALITY_RANK.get(e["materiality"], 2), e["y_new"], e["change_id"]
    ))
    pool = pool[:max_items]

    for i, e in enumerate(pool, 1):
        e["label"] = f"E{i}"
    return pool


def format_evidence_block(pool: list[dict]) -> str:
    """Render the evidence pool as the numbered block the narrator reads."""
    blocks = []
    for e in pool:
        lines = [f"[{e['label']}] {e['section_name']} · {e['y_old']} -> {e['y_new']}"]
        if e["summary"]:
            lines.append(f"  what changed: {e['summary']}")
        if e["why_it_matters"]:
            lines.append(f"  why: {e['why_it_matters']}")
        if e["old_quote"]:
            lines.append(f'  was: "{e["old_quote"]}"')
        if e["new_quote"]:
            lines.append(f'  now: "{e["new_quote"]}"')
        g = e.get("numeric_guard")
        if g and g.get("pct") is not None:
            lines.append(f"  numeric move: {g.get('old')} -> {g.get('new')} "
                         f"({g['pct'] * 100:+.0f}%)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_xbrl_block(metric_series: dict, tags: list[str], labels: dict,
                      years: list[str], fmt_value) -> str:
    """Render selected metric series as a compact text table for prompt grounding."""
    rows = []
    for tag in tags:
        series = metric_series.get(tag)
        if not series:
            continue
        cells = []
        for fy in years:
            d = series.get(fy) or {}
            if d.get("value") is None:
                continue
            cell = f"{fy} {fmt_value(d['value'], tag)}"
            if d.get("pct") is not None:
                cell += f" ({d['pct']:+.1f}%)"
            cells.append(cell)
        if cells:
            rows.append(f"{labels.get(tag, tag)}: " + "; ".join(cells))
    if not rows:
        return ""
    return "AUDITED FIGURES (from XBRL — these are exact, use them):\n" + "\n".join(rows)


def parse_narrative_response(raw: str) -> tuple[str, list[str]]:
    """Split the delimiter-framed LLM response into prose and pull-quote labels.

    Long prose is framed by delimiters rather than JSON: a multi-paragraph
    narrative inside a JSON string field invites escaping errors that cost a
    whole chapter.
    """
    if not raw or raw.startswith("[TIMEOUT]") or raw.startswith("[ERROR"):
        return "", []

    text = _drop_dangling_sentence(raw.strip())

    pull_labels = []
    m = re.search(r"PULL_QUOTES\s*:\s*(.*)", text, re.IGNORECASE)
    if m:
        pull_labels = re.findall(r"E\d+", m.group(1))
        text = text[:m.start()]

    m = re.search(r"NARRATIVE\s*:\s*", text, re.IGNORECASE)
    if m:
        text = text[m.end():]

    # A model that ignores the format spec still hands back usable prose; only
    # strip a stray EVIDENCE echo if it appears.
    text = re.split(r"\nEVIDENCE\s*:", text, maxsplit=1)[0]

    return text.strip(), pull_labels


def resolve_citations(text: str, pool: list[dict]) -> tuple[list[str], list[dict]]:
    """Convert [E7] markers into numbered superscripts and collect footnotes.

    Footnotes are numbered by order of first appearance in the prose, not by
    evidence-pool order, so the reader's eye and the drawer agree. Labels not
    present in the pool are dropped silently — the same fail-safe as an
    unvalidated quote.

    Returns (paragraph_html_list, footnotes).
    """
    by_label = {e["label"]: e for e in pool}
    order = {}
    footnotes = []

    def _sub(m):
        label = f"E{m.group(1)}"
        e = by_label.get(label)
        if e is None:
            return ""
        if label not in order:
            order[label] = len(order) + 1
            fn = dict(e)
            fn["n"] = order[label]
            footnotes.append(fn)
        n = order[label]
        return (f'<sup class="cite"><a href="#ev-{e["change_id"]}" '
                f'title="{html.escape(e["section_name"])} · {e["y_old"]}&rarr;{e["y_new"]}">'
                f'{n}</a></sup>')

    paragraphs = []
    for raw_para in re.split(r"\n\s*\n", text):
        para = raw_para.strip()
        if not para:
            continue
        # Escape first, then inject markup: escaping leaves [E7] untouched, so
        # citation substitution cannot be spoofed by model-emitted HTML.
        para = html.escape(para).replace("\n", " ")
        paragraphs.append(CITE_RE.sub(_sub, para))

    return paragraphs, footnotes


def _interleave_pull_quotes(paragraphs: list[str], pull_quotes: list[dict]) -> list[dict]:
    """Distribute pull-quotes between paragraphs as renderable blocks."""
    blocks = [{"type": "p", "html": p} for p in paragraphs]
    if not pull_quotes or len(blocks) < 3:
        return blocks

    step = max(2, len(blocks) // (len(pull_quotes) + 1))
    out = []
    q = list(pull_quotes)
    for i, b in enumerate(blocks):
        out.append(b)
        if q and i > 0 and (i + 1) % step == 0 and i < len(blocks) - 1:
            out.append({"type": "pullquote", "quote": q.pop(0)})
    return out


def compose_chapter(chapter: dict, interpretations: dict, ticker: str,
                    entity: str, year_range: str, xbrl_block: str = "",
                    timeout: int = 240) -> dict | None:
    """Compose one chapter's narrative. Returns None if there is nothing to say."""
    pool = build_evidence_pool(interpretations, chapter["anchors"])
    if not pool:
        return None

    prompt = CHAPTER_NARRATIVE_PROMPT.format(
        entity=entity,
        ticker=ticker,
        year_range=year_range,
        chapter_title=chapter["title"],
        chapter_subtitle=chapter["subtitle"],
        xbrl_block=xbrl_block,
        min_words=NARRATIVE_MIN_WORDS,
        max_words=NARRATIVE_MAX_WORDS,
        evidence_block=format_evidence_block(pool),
    )

    raw = call_llm(prompt, timeout=timeout, system=SYSTEM_PROSE,
                   max_tokens=NARRATIVE_MAX_TOKENS)
    text, pull_labels = parse_narrative_response(raw)
    if not text:
        return None

    paragraphs, footnotes = resolve_citations(text, pool)
    if not paragraphs:
        return None

    by_label = {e["label"]: e for e in pool}
    pull_quotes = [by_label[l] for l in pull_labels[:2]
                   if l in by_label and by_label[l].get("new_quote")]

    word_count = len(re.findall(r"\b\w+\b", CITE_RE.sub("", text)))

    return {
        "id": chapter["id"],
        "title": chapter["title"],
        "subtitle": chapter["subtitle"],
        "blocks": _interleave_pull_quotes(paragraphs, pull_quotes),
        "footnotes": footnotes,
        "n_evidence": len(pool),
        "n_cited": len(footnotes),
        "word_count": word_count,
    }


def narrate_ticker(ticker: str, entity: str, interpretations: dict,
                   metric_series: dict, years: list[str],
                   chapters_cfg=None, financials_anchors=None,
                   verbose: bool = True) -> tuple[list[dict], list[str], dict | None]:
    """Compose every chapter, the financial narrative, and the executive summary.

    Returns (chapters, exec_summary, financial_narrative).
    """
    from config import (REPORT_CHAPTERS, FINANCIALS_NARRATIVE_ANCHORS,
                        XBRL_STATEMENT_GROUPS)
    from delta.report import XBRL_LABELS, _fmt_money

    if chapters_cfg is None:
        chapters_cfg = REPORT_CHAPTERS
    if financials_anchors is None:
        financials_anchors = FINANCIALS_NARRATIVE_ANCHORS

    # State the count explicitly: GOOGL (3 years) and META (2) have shorter CIK
    # histories than the 5-year default, and the model otherwise assumed five.
    year_range = f"{years[0]} to {years[-1]} ({len(years)} fiscal years)" if years else ""

    # Headline metrics ground every chapter; the financial chapter gets the lot.
    headline_tags = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                     "Revenues", "OperatingIncomeLoss", "NetIncomeLoss",
                     "NetCashProvidedByUsedInOperatingActivities"]
    all_tags = [t for _, tags in XBRL_STATEMENT_GROUPS for t in tags]

    headline_block = format_xbrl_block(metric_series, headline_tags,
                                       XBRL_LABELS, years, _fmt_money)
    full_block = format_xbrl_block(metric_series, all_tags,
                                   XBRL_LABELS, years, _fmt_money)

    financial_narrative = None
    if financials_anchors:
        fin_chapter = {
            "id": "financials-narrative",
            "title": "Financial Performance",
            "subtitle": "What the numbers did, and how the filing explained them",
            "anchors": financials_anchors,
        }
        if verbose:
            print("    Financial Performance... ", end="", flush=True)
        financial_narrative = compose_chapter(
            fin_chapter, interpretations, ticker, entity, year_range, full_block
        )
        if verbose:
            print(f"{financial_narrative['word_count']} words, "
                  f"{financial_narrative['n_cited']} cited"
                  if financial_narrative else "no evidence, skipped")

    chapters = []
    for cfg in chapters_cfg:
        if verbose:
            print(f"    {cfg['title']}... ", end="", flush=True)
        ch = compose_chapter(cfg, interpretations, ticker, entity,
                             year_range, headline_block)
        if ch:
            chapters.append(ch)
            if verbose:
                print(f"{ch['word_count']} words, {ch['n_cited']}/{ch['n_evidence']} cited")
        elif verbose:
            print("no evidence, skipped")

    if verbose:
        print("    Executive Summary... ", end="", flush=True)
    summary_input = ([financial_narrative] if financial_narrative else []) + chapters
    exec_summary = compose_exec_summary(summary_input, ticker, entity,
                                        year_range, headline_block)
    if verbose:
        print(f"{sum(len(p.split()) for p in exec_summary)} words"
              if exec_summary else "skipped")

    return chapters, exec_summary, financial_narrative


def compose_exec_summary(chapters: list[dict], ticker: str, entity: str,
                         year_range: str, xbrl_block: str = "",
                         timeout: int = 240) -> list[str]:
    """Compose the executive summary from the finished chapters."""
    if not chapters:
        return []

    parts = []
    for ch in chapters:
        prose = " ".join(
            CITE_RE.sub("", html.unescape(re.sub(r"<[^>]+>", "", b["html"])))
            for b in ch["blocks"] if b["type"] == "p"
        )
        parts.append(f"## {ch['title']}\n{prose.strip()}")

    prompt = EXEC_SUMMARY_PROMPT.format(
        entity=entity,
        ticker=ticker,
        year_range=year_range,
        xbrl_block=xbrl_block,
        min_words=180,
        max_words=320,
        chapters_block="\n\n".join(parts),
    )

    raw = call_llm(prompt, timeout=timeout, system=SYSTEM_PROSE,
                   max_tokens=NARRATIVE_MAX_TOKENS)
    if not raw or raw.startswith("[TIMEOUT]") or raw.startswith("[ERROR"):
        return []

    text = _drop_dangling_sentence(raw.strip())
    text = re.sub(r"^\s*(EXECUTIVE SUMMARY|SUMMARY)\s*:?\s*", "", text,
                  flags=re.IGNORECASE)
    return [html.escape(p.strip()).replace("\n", " ")
            for p in re.split(r"\n\s*\n", text) if p.strip()]
