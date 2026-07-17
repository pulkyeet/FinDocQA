"""Prompt templates for Delta LLM interpretation and trend synthesis."""

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


SYNTHESIS_PROMPT = """You are writing a longitudinal narrative for {ticker}'s {section_name}
section across {year_range}. Below are the interpreted changes for each year pair.

Write a 3-to-6 sentence narrative tracing how this section evolved over time.
Reference specific changes, their timing, and their direction (appeared, expanded,
softened, removed).

Rules:
- Use ONLY the provided interpretation records. Do not infer changes not shown.
- Do not use outside knowledge of the company.
- Be specific: name what changed and when, not vague generalities.

Interpretations:
{interpretations_json}"""
