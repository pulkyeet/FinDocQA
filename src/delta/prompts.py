"""Prompt templates for Delta LLM interpretation (stage 7) and narrative
composition (stage 8)."""

INTERPRETATION_PROMPT = """You are analyzing changes in {ticker}'s 10-K, section {section_name},
FY{y1} vs FY{y2}. Below are passage pairs a deterministic diff engine flagged as changed,
plus whole-passage additions and removals. Numeric context from XBRL: {xbrl_text}.

For each change_id, output a JSON object:
- change_id: the change_id as given
- change_type: added | removed | expanded | softened | strengthened | reworded
- materiality: boilerplate | notable | material
- summary: one sentence stating what changed
- why_it_matters: one sentence, ONLY for notable/material; else null
- old_quote / new_quote: shortest exact excerpts evidencing the change
  (must be verbatim substrings of the provided text)

Output format: a JSON array. Example:
[
  {{
    "change_id": "AAPL-item1a_risk-FY2024-FY2025-008",
    "change_type": "expanded",
    "materiality": "material",
    "summary": "AI competition risk expanded with litigation language",
    "why_it_matters": "First litigation-specific framing of AI risk.",
    "old_quote": "competition in machine learning",
    "new_quote": "litigation relating to training data provenance"
  }}
]

Rules:
- Judge ONLY from the provided text and XBRL context. Do not use outside
  knowledge of the company. Do not infer changes not shown.
- Date rolls, fiscal-period updates, repagination, and pure restyling are
  boilerplate.
- "Material" is reserved for changes a portfolio manager would want
  surfaced: new or removed risk factors, tone shifts on named business
  drivers, litigation/regulatory language changes, guidance-adjacent
  language, segment framing changes.
- If a flagged pair shows no substantive difference, classify it
  boilerplate with summary "no substantive change".
- old_quote and new_quote MUST be copied character-for-character from the provided
  old_text and new_text fields. Do not rephrase, abbreviate, or normalize whitespace.
  If you cannot produce an exact verbatim excerpt, set both quotes to empty strings.
Output: a JSON array of objects, nothing else.

Changes:
{changes_json}"""


CHAPTER_NARRATIVE_PROMPT = """You are a senior equity analyst writing one chapter of a
multi-year change report on {entity} ({ticker}), covering {year_range}.

Chapter: **{chapter_title}** — {chapter_subtitle}

Your only source is the numbered evidence below. Each item is a verified change
between two consecutive 10-K filings, found by a deterministic diff engine: the
"was"/"now" quotes are verbatim filing text, not paraphrase.

{xbrl_block}

Write {min_words}-{max_words} words of flowing analytical prose.

WHAT TO WRITE ABOUT — the substance of the change, not its bookkeeping:
- Say what the company actually did, feared, gained, or lost. "Apple began
  disclosing India as a named growth market in FY2023, having previously
  grouped it under Rest of Asia Pacific" — not "the segment paragraph was
  modified."
- Trace direction and timing across the period covered. Never assert a span
  other than {year_range} — some companies have shorter filing histories.
  When did a theme first
  appear? Did it intensify, soften, or vanish? A risk that appears in FY2022
  and is gone by FY2025 is a story.
- Group by theme (supply chain, AI, regulation, a named geography, pricing
  power, litigation), not by year and not by filing paragraph.
- Where numbers are given above, tie the language change to the number. Prose
  hardening while the metric deteriorates is the single most valuable
  observation you can make.

HARD RULES:
- Every substantive claim must carry a citation in the form [E7]. Cite the
  evidence item that supports it. Multiple: [E7][E12].
- Use ONLY the evidence and figures provided. You have no outside knowledge of
  this company. Never invent a number, date, product, or place not present above.
- Never mention the diff engine, similarity scores, classifications, change
  types, materiality labels, or the words "evidence item". The reader is
  looking at a finance report, not a tool's output.
- No headings, no bullet lists, no markdown. Continuous paragraphs separated by
  a blank line.
- Never use an em dash (—). Use a comma, colon, semicolon, or period instead.
- If the evidence is thin, write a shorter, honest chapter. Do not pad.

Then choose up to 2 evidence items whose was/now contrast is most striking to
display as pull-quotes.

OUTPUT FORMAT — exactly this, nothing else:
NARRATIVE:
<your prose>

PULL_QUOTES: E3, E12

EVIDENCE:
{evidence_block}"""


EXEC_SUMMARY_PROMPT = """You are a senior equity analyst. Below are the chapters of a
multi-year change report on {entity} ({ticker}), covering {year_range}, plus the
audited financial series.

{xbrl_block}

Write the executive summary: {min_words}-{max_words} words, 3-4 paragraphs.

- Lead with the single most consequential shift across the period covered.
  Never assert a span other than {year_range}.
- Name the two or three themes that run through multiple chapters.
- Where the numbers and the language disagree, say so plainly.
- No headings, no bullets, no markdown. No citations. Do not mention the diff
  engine or how the report was produced.
- Never use an em dash (—). Use a comma, colon, semicolon, or period instead.
- Use ONLY what is below. Invent nothing.

Output the summary text and nothing else.

CHAPTERS:
{chapters_block}"""
