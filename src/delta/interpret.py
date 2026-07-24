"""Stages 7-8: LLM interpretation of diff records and trend synthesis."""

import json
import re
import subprocess

import requests as _requests

from config import (
    OPENCODE_AGENT, OPENCODE_ATTACH,
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL,
    sanitize_prompt,
)
from delta.prompts import INTERPRETATION_PROMPT, SYNTHESIS_PROMPT
from delta.xbrl_delta import deltas_for_section, format_xbrl_context

VALID_CHANGE_TYPES = {"added", "removed", "expanded", "softened", "strengthened", "reworded"}
VALID_MATERIALITIES = {"boilerplate", "notable", "material"}


def call_llm(prompt: str, timeout: int = 60) -> str:
    """Call LLM via OpenRouter API. Falls back to opencode subprocess if no API key."""
    prompt = sanitize_prompt(prompt)

    if OPENROUTER_API_KEY:
        return _call_openrouter(prompt, timeout)

    return _call_opencode(prompt, timeout)


def _call_openrouter(prompt: str, timeout: int) -> str:
    """Call OpenRouter API with OpenAI-compatible chat format."""
    try:
        resp = _requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a precise financial document analyst. Output only valid JSON. Copy quotes verbatim."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 4096,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()
    except _requests.exceptions.Timeout:
        return "[TIMEOUT]"
    except Exception as e:
        return f"[ERROR: {str(e)[:200]}]"


def _call_opencode(prompt: str, timeout: int) -> str:
    """Fallback: call opencode run --agent as subprocess."""
    try:
        base_cmd = ["opencode", "run", "--agent", OPENCODE_AGENT]
        attach = OPENCODE_ATTACH or "http://localhost:4096"
        if attach:
            base_cmd += ["--attach", attach]
        proc = subprocess.Popen(
            base_cmd + [prompt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return "[TIMEOUT]"
        if proc.returncode != 0:
            return f"[ERROR: {err[:200]}]"
        out = re.sub(r"^\x1b\[.*?m", "", out, flags=re.MULTILINE)
        lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("> ")]
        return "\n".join(lines).strip()
    except Exception as e:
        return f"[ERROR: {str(e)[:200]}]"


def validate_interpretation(record: dict, diff_record: dict) -> tuple[bool, str]:
    """Validate an interpretation against its diff record.

    - change_id must match
    - old_quote in diff_record.old_text (verbatim substring)
    - new_quote in diff_record.new_text (verbatim substring)
    - change_type and materiality must be valid enums

    Returns (is_valid, error_message).
    """
    if record.get("change_id") != diff_record.get("change_id"):
        if diff_record.get("change_id", "").endswith("-000"):
            pass
        else:
            return False, f"change_id mismatch: {record.get('change_id')} vs {diff_record.get('change_id')}"

    old_text = diff_record.get("old_text", "")
    new_text = diff_record.get("new_text", "")

    old_quote = record.get("old_quote", "")
    new_quote = record.get("new_quote", "")

    if old_quote and old_quote not in old_text:
        return False, f"old_quote not in old_text: {old_quote[:50]!r}"

    if new_quote and new_quote not in new_text:
        return False, f"new_quote not in new_text: {new_quote[:50]!r}"

    if record.get("change_type") not in VALID_CHANGE_TYPES:
        return False, f"invalid change_type: {record.get('change_type')}"

    if record.get("materiality") not in VALID_MATERIALITIES:
        return False, f"invalid materiality: {record.get('materiality')}"

    return True, ""


def interpret_section_pair(diff_records: list[dict], xbrl_deltas: dict,
                           ticker: str, anchor: str, year_pair: tuple,
                           section_names: dict[str, str] | None = None,
                             timeout: int = 120) -> list[dict]:
    """Stage 7: send changed records to LLM, parse JSON, validate.

    Returns list of interpretation records (validated + unvalidated-flagged).
    """
    if section_names is None:
        section_names = {}

    y_old, y_new = year_pair

    changes = []
    for r in diff_records:
        cls = r.get("classification", "")
        if cls == "unchanged":
            continue
        old_text = r.get("old_text", "")
        new_text = r.get("new_text", "")
        entry = {
            "change_id": r.get("change_id", ""),
            "classification": cls,
            "old_text": old_text[:500],
            "new_text": new_text[:500],
        }
        changes.append(entry)

    if not changes:
        return []

    section_name = section_names.get(anchor, anchor)
    xbrl_context = deltas_for_section(xbrl_deltas, anchor)
    xbrl_text = format_xbrl_context(xbrl_context)
    diff_map = {r.get("change_id", ""): r for r in diff_records}

    BATCH_SIZE = 5
    batches = [changes[i:i+BATCH_SIZE] for i in range(0, len(changes), BATCH_SIZE)]

    all_results = []
    for batch in batches:
        changes_json = json.dumps(batch, indent=2)
        prompt = INTERPRETATION_PROMPT.format(
            ticker=ticker,
            section_name=section_name,
            y1=y_old,
            y2=y_new,
            xbrl_text=xbrl_text,
            changes_json=changes_json,
        )

        raw_response = call_llm(prompt, timeout=timeout)

        if raw_response.startswith("[TIMEOUT]") or raw_response.startswith("[ERROR"):
            for ch in batch:
                all_results.append({
                    "change_id": ch["change_id"],
                    "change_type": "reworded",
                    "materiality": "boilerplate",
                    "summary": f"LLM call failed: {raw_response}",
                    "why_it_matters": None,
                    "old_quote": "",
                    "new_quote": "",
                    "_unvalidated": True,
                })
            continue

        try:
            parsed = _parse_json_from_response(raw_response)
        except Exception:
            parsed = []

        results = []
        for interp in parsed:
            cid = interp.get("change_id", "")
            diff_rec = diff_map.get(cid, {})
            valid, error = validate_interpretation(interp, diff_rec)
            if not valid:
                interp["_unvalidated"] = True
                interp["_validation_error"] = error
            results.append(interp)

        cids_from_llm = {r.get("change_id") for r in parsed}
        for ch in batch:
            if ch["change_id"] not in cids_from_llm:
                results.append({
                    "change_id": ch["change_id"],
                    "change_type": "reworded",
                    "materiality": "boilerplate",
                    "summary": "LLM did not interpret this change",
                    "why_it_matters": None,
                    "old_quote": "",
                    "new_quote": "",
                    "_unvalidated": True,
                })

        unvalidated = [r for r in results if r.get("_unvalidated")]
        if unvalidated:
            retry_prompt = (
                "Your previous response had validation errors. Please fix and re-output.\n"
                "Specifically, old_quote MUST be a verbatim substring of old_text, and "
                "new_quote MUST be a verbatim substring of new_text. Copy them exactly.\n\n"
                + prompt
            )
            raw_retry = call_llm(retry_prompt, timeout=timeout)
            try:
                retry_parsed = _parse_json_from_response(raw_retry)
            except Exception:
                retry_parsed = []

            retry_map = {r.get("change_id"): r for r in retry_parsed}
            for interp in results:
                if interp.get("_unvalidated"):
                    cid = interp["change_id"]
                    if cid in retry_map:
                        retry_interp = retry_map[cid]
                        diff_rec = diff_map.get(cid, {})
                        retry_valid, retry_error = validate_interpretation(retry_interp, diff_rec)
                        if retry_valid:
                            retry_interp["_validated_on_retry"] = True
                            interp.clear()
                            interp.update(retry_interp)
                            interp["_unvalidated"] = False
                        else:
                            interp["_validation_error"] = retry_error

        all_results.extend(results)

    return all_results


def interpret_ticker(ticker: str, records_by_year: dict, xbrl_deltas: dict,
                     section_names: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """Run LLM interpretation for all year pairs and sections for a ticker.

    Returns {anchor: [interpretation_records, ...]}.
    """
    all_interpretations: dict[str, list[dict]] = {}
    for (y_old, y_new), diff_records in sorted(records_by_year.items()):
        sections = {}
        for r in diff_records:
            anchor = r.get("anchor")
            if anchor:
                sections.setdefault(anchor, []).append(r)

        for anchor, sec_records in sections.items():
            n_changed = sum(1 for r in sec_records if r.get("classification") != "unchanged")
            if n_changed == 0:
                continue
            print(f"    {anchor} ({n_changed} changed)... ", end="", flush=True)
            interps = interpret_section_pair(
                sec_records, xbrl_deltas, ticker, anchor, (y_old, y_new),
                section_names=section_names
            )
            n_valid = sum(1 for ir in interps if not ir.get("_unvalidated"))
            print(f"{len(interps)} interps, {n_valid} OK")
            for ir in interps:
                ir["_y_old"] = y_old
                ir["_y_new"] = y_new
                # Attach churn context
                changed = [r for r in sec_records if r["classification"] != "unchanged"]
                matched = [r for r in sec_records if r["classification"] not in ("added", "removed")]
                from delta.diff import compute_churn_score
                classifications = [r["classification"] for r in matched]
                ir["_churn"] = compute_churn_score(
                    matched if matched else [{"old_text": "", "new_text": ""}],
                    classifications if classifications else ["unchanged"]
                )
            all_interpretations.setdefault(anchor, []).extend(interps)

    return all_interpretations


def synthesize_trend(interpretations: list[dict], anchor: str, year_pairs: list,
                     section_names: dict[str, str] | None = None, timeout: int = 180) -> str:
    """Stage 8: one LLM call per section, longitudinal narrative."""
    if section_names is None:
        section_names = {}

    valid = [ir for ir in interpretations if not ir.get("_unvalidated")]
    if len(valid) < 2:
        return ""

    section_name = section_names.get(anchor, anchor)
    years = []
    for y_old, y_new in year_pairs:
        years.extend([y_old, y_new])
    year_range = f"{years[0]} to {years[-1]}"

    interps_for_prompt = []
    for ir in valid:
        interps_for_prompt.append({
            "change_id": ir.get("change_id"),
            "change_type": ir.get("change_type"),
            "materiality": ir.get("materiality"),
            "summary": ir.get("summary"),
            "why_it_matters": ir.get("why_it_matters"),
        })

    interpretations_json = json.dumps(interps_for_prompt, indent=2)

    prompt = SYNTHESIS_PROMPT.format(
        ticker="this company",
        section_name=section_name,
        year_range=year_range,
        interpretations_json=interpretations_json,
    )

    raw = call_llm(prompt, timeout=timeout)
    if raw.startswith("[TIMEOUT]") or raw.startswith("[ERROR"):
        return ""

    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "narrative" in parsed:
            raw = parsed["narrative"]
    except (json.JSONDecodeError, TypeError):
        pass

    return raw


def synthesize_trends(ticker: str, interpretations: dict[str, list[dict]],
                      section_names: dict[str, str] | None,
                      year_pairs: list) -> dict[str, str]:
    """Run trend synthesis for all sections with enough interpretations."""
    trends = {}
    for anchor, interps in sorted(interpretations.items()):
        trends[anchor] = synthesize_trend(
            interps, anchor, year_pairs, section_names=section_names
        )
    return trends


def _parse_json_from_response(response: str) -> list:
    """Extract and parse JSON array from LLM response text."""
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        response = "\n".join(lines)

    try:
        parsed = json.loads(response)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", response, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return []
