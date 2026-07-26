"""Stage 6: YoY XBRL numeric deltas from companyfacts JSON."""

import json
import os

from config import RAW_DIR
from fetch import fiscal_year_label
from anchors import XBRL_TAG_TO_ANCHOR


def load_companyfacts(ticker: str) -> dict:
    """Load {ticker}_companyfacts.json from raw data."""
    path = f"{RAW_DIR}/{ticker}_companyfacts.json"
    with open(path) as f:
        return json.load(f)


def get_xbrl_values(companyfacts: dict, tag: str, concept_type: str = "us-gaap") -> list[dict]:
    """Extract all filed values for a tag from companyfacts JSON.

    Returns list of {end, val, unit, fy} sorted by end date descending.
    """
    facts = companyfacts.get("facts", {}).get(concept_type, {}).get(tag, {})
    units = facts.get("units", {})
    results = []
    for unit_key, entries in units.items():
        for entry in entries:
            if "val" not in entry or "end" not in entry:
                continue
            fy = fiscal_year_label(entry["end"])
            results.append({
                "end": entry["end"],
                "val": entry["val"],
                "unit": unit_key,
                "fy": fy,
                "form": entry.get("form", ""),
            })
    results.sort(key=lambda x: x["end"], reverse=True)
    return results


def fiscal_year_value(values: list[dict], fiscal_year: str) -> float | None:
    """Get the annual (10-K) value for a specific fiscal year.

    Prefers entries with form='10-K', falls back to any entry for the FY.
    """
    candidates = [v for v in values if v["fy"] == fiscal_year]
    if not candidates:
        return None
    annual = [v for v in candidates if v.get("form") == "10-K"]
    if annual:
        annual.sort(key=lambda x: x["val"], reverse=True)
        return annual[0]["val"]
    return max(candidates, key=lambda x: x["val"])["val"]


def compute_yoy_deltas(companyfacts: dict, tags: list[str], year_range: list[str]) -> dict:
    """For each tag, compute YoY deltas across the year range.

    Returns {tag: {year_pair_str: {old, new, abs_change, pct_change}}}.
    year_pair_str is e.g. 'FY2024-FY2025'.
    """
    result = {}
    sorted_years = sorted(year_range)
    for tag in tags:
        values = get_xbrl_values(companyfacts, tag)
        tag_deltas = {}
        for i in range(len(sorted_years) - 1):
            y_old = sorted_years[i]
            y_new = sorted_years[i + 1]
            old_val = fiscal_year_value(values, y_old)
            new_val = fiscal_year_value(values, y_new)
            if old_val is None and new_val is None:
                continue
            yp = f"{y_old}-{y_new}"
            delta_entry = {"old": old_val, "new": new_val}
            if old_val is not None and new_val is not None:
                delta_entry["abs_change"] = new_val - old_val
                if abs(old_val) > 0:
                    delta_entry["pct_change"] = round((new_val - old_val) / abs(old_val) * 100, 2)
                else:
                    delta_entry["pct_change"] = None
            elif new_val is not None:
                delta_entry["abs_change"] = new_val
                delta_entry["pct_change"] = None
            elif old_val is not None:
                delta_entry["abs_change"] = -old_val
                delta_entry["pct_change"] = None
            tag_deltas[yp] = delta_entry
        if tag_deltas:
            result[tag] = tag_deltas
    return result


def build_metric_series(companyfacts: dict, tags: list[str], year_range: list[str]) -> dict:
    """Absolute value per fiscal year for each tag, with YoY % vs the prior year.

    Unlike compute_yoy_deltas (which is keyed by year *pair* and drives the
    numeric guard), this is keyed by year and drives the report's financial
    tables: every year's number is shown, with its change in brackets.

    Returns {tag: {fy: {"value": float|None, "pct": float|None}}}.
    Tags with no value in any year are omitted.
    """
    sorted_years = sorted(year_range)
    series = {}
    for tag in tags:
        values = get_xbrl_values(companyfacts, tag)
        by_year = {}
        prev = None
        found_any = False
        for fy in sorted_years:
            val = fiscal_year_value(values, fy)
            if val is not None:
                found_any = True
            pct = None
            if val is not None and prev is not None and abs(prev) > 0:
                pct = round((val - prev) / abs(prev) * 100, 2)
            by_year[fy] = {"value": val, "pct": pct}
            # Only carry a real value forward, so a one-year gap doesn't
            # silently compare FY2025 against FY2023 as if it were YoY.
            prev = val if val is not None else None
        if found_any:
            series[tag] = by_year
    return series


def deltas_for_section(xbrl_deltas: dict, anchor: str) -> dict:
    """Filter XBRL deltas to tags relevant to a section anchor."""
    relevant_tags = [tag for tag, a in XBRL_TAG_TO_ANCHOR.items() if a == anchor]
    filtered = {}
    for tag in relevant_tags:
        if tag in xbrl_deltas:
            filtered[tag] = xbrl_deltas[tag]
    return filtered


def format_xbrl_context(deltas: dict) -> str:
    """Format XBRL deltas as human-readable text for LLM prompt context."""
    if not deltas:
        return "No XBRL numeric context available."
    lines = []
    for tag, yp_deltas in sorted(deltas.items()):
        for yp, d in sorted(yp_deltas.items()):
            old_str = f"{d['old']:,.0f}" if d.get("old") is not None else "N/A"
            new_str = f"{d['new']:,.0f}" if d.get("new") is not None else "N/A"
            pct_str = f" ({d['pct_change']:+.1f}%)" if d.get("pct_change") is not None else ""
            lines.append(f"{tag} {yp}: {old_str} -> {new_str}{pct_str}")
    return "\n".join(lines)
