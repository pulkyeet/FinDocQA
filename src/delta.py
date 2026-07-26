"""Delta CLI entrypoint: python delta.py TICKER [--years N] [--no-llm]

Full pipeline:
  1. fetch N years (if not cached)
  2. chunk each year (if not cached)
  3. for each consecutive year pair:
     a. align sections (anchor equality)
     b. align paragraphs (embeddings)
     c. diff classify -> diff records
     d. XBRL delta computation
     e. LLM interpretation (unless --no-llm)
  4. print CLI summary table
"""

import argparse
import json
import os
import sys

from anchors import SECTION_NAMES
from config import TICKERS, DELTA_YEARS_DEFAULT, DELTA_YEARS_MAX
from fetch import find_n_recent_10ks, fetch_10k_html_for_year, fetch_companyfacts
from chunk import chunk_sectionaware, _write_chunks
from delta.align import load_chunks_for_year
from delta.diff import diff_all_sections, write_diff_records, churn_summary, classification_counts
from delta.xbrl_delta import load_companyfacts, compute_yoy_deltas, build_metric_series
from delta.report import (
    build_report_data, render_html, render_cli_summary, write_report,
    write_interpretations, write_narratives, build_report_index,
)
from config import XBRL_DELTA_TAGS, DELTA_REPORTS_DIR


def fetch_ticker(ticker, cik, years):
    fetch_companyfacts(ticker, cik)
    records = find_n_recent_10ks(ticker, cik, years)
    for rec in records:
        fetch_10k_html_for_year(
            ticker, cik,
            rec["accession_no"], rec["doc_filename"],
            rec["period_end"], rec["entity_name"], rec["fiscal_year"],
        )
    return records


def chunk_ticker(ticker, fys):
    from config import CHUNKS_DIR
    for fy in fys:
        html_path = f"data/raw/{ticker}_{fy}_10k.html"
        meta_path = html_path.replace("_10k.html", "_10k_meta.json")
        chunk_path = f"{CHUNKS_DIR}/{ticker}_{fy}_sectionaware.json"
        if os.path.exists(chunk_path):
            continue
        if not os.path.exists(html_path):
            print(f"[warn] {ticker} {fy}: raw 10-K missing, skipping chunk")
            continue
        with open(meta_path) as f:
            period_end = json.load(f)["period_end"]
        chunks = chunk_sectionaware(html_path, ticker, period_end)
        _write_chunks(chunk_path, chunks)
        print(f"[sectionaware] {ticker} {fy}: {len(chunks)} chunks")


def run_delta(ticker, years, no_llm=False):
    cik = TICKERS[ticker]

    print(f"\n{'='*60}")
    print(f"Delta pipeline: {ticker} ({years} years)")
    print(f"{'='*60}")

    print(f"\n[stage 1-2] fetch + chunk...")
    meta_records = fetch_ticker(ticker, cik, years)
    fys = [r["fiscal_year"] for r in meta_records]
    entity_name = meta_records[0].get("entity_name", ticker) if meta_records else ticker
    chunk_ticker(ticker, fys)

    chunks_by_year = {}
    for fy in fys:
        try:
            chunks_by_year[fy] = load_chunks_for_year(ticker, fy)
            print(f"  {ticker} {fy}: {len(chunks_by_year[fy])} chunks")
        except FileNotFoundError:
            print(f"  [warn] {ticker} {fy}: chunks missing, skipping")
            continue

    available_fys = sorted(chunks_by_year.keys())
    if len(available_fys) < 2:
        print(f"[error] need at least 2 years of chunks, got {len(available_fys)}")
        return

    print(f"\n[stage 6] XBRL deltas (numeric guard + LLM context)...")
    # Computed before diff so the numeric guard can corroborate audited metric
    # moves during classification. Cheap + deterministic; also aids --no-llm.
    try:
        xbrl_data = load_companyfacts(ticker)
        xbrl_deltas = compute_yoy_deltas(xbrl_data, XBRL_DELTA_TAGS, available_fys)
        metric_series = build_metric_series(xbrl_data, XBRL_DELTA_TAGS, available_fys)
        n_tags = len([k for k, v in xbrl_deltas.items() if v])
        print(f"  {n_tags} tags with YoY deltas across {len(available_fys)} years")
    except FileNotFoundError:
        xbrl_deltas = {}
        metric_series = {}
        print(f"  [warn] companyfacts missing; numeric guard runs text-only")

    print(f"\n[stage 3-5] align + diff...")
    year_pairs = [(available_fys[i], available_fys[i + 1]) for i in range(len(available_fys) - 1)]

    records_by_year = {}
    for y_old, y_new in year_pairs:
        print(f"\n  {y_old} -> {y_new}")
        all_records = diff_all_sections(
            chunks_by_year[y_old], chunks_by_year[y_new],
            ticker, (y_old, y_new), xbrl_deltas=xbrl_deltas,
        )
        write_diff_records(all_records, ticker, y_old, y_new)
        records_by_year[(y_old, y_new)] = all_records
        n_changed = sum(1 for r in all_records if r["classification"] != "unchanged")
        n_guard = sum(1 for r in all_records if r.get("numeric_guard"))
        print(f"    {len(all_records)} diff records, {n_changed} changed ({n_guard} via numeric guard)")

    print(churn_summary(ticker, records_by_year, SECTION_NAMES))

    if not no_llm:
        print(f"\n[stage 7] LLM interpretation...")
        from delta.interpret import interpret_ticker
        from delta.narrate import narrate_ticker

        interpretations = interpret_ticker(
            ticker, records_by_year, xbrl_deltas, SECTION_NAMES
        )
        n_interp = sum(len(v) for v in interpretations.values())
        n_valid = sum(
            sum(1 for ir in v if not ir.get("_unvalidated"))
            for v in interpretations.values()
        )
        print(f"\n  Total: {n_interp} interpretations ({n_valid} validated)")
        write_interpretations(interpretations, ticker)

        print(f"\n[stage 8] Narrative composition...")
        chapters, exec_summary, financial_narrative = narrate_ticker(
            ticker, entity_name, interpretations, metric_series, available_fys,
        )
        write_narratives(chapters, exec_summary, financial_narrative, ticker)

        print(f"\n[stage 9] Report rendering...")
        report_data = build_report_data(
            ticker, records_by_year, interpretations, xbrl_deltas,
            metric_series=metric_series, chapters=chapters,
            exec_summary=exec_summary, financial_narrative=financial_narrative,
            entity_name=entity_name,
        )

        html = render_html(report_data)
        report_path = write_report(ticker, html)
        print(f"  Report written: {report_path}")

        print(render_cli_summary(report_data))

    print(f"\n[complete] Delta pipeline finished for {ticker}")


def _write_report_index(tickers):
    """Write data/reports/index.html listing all ticker reports."""
    import os
    html = build_report_index(tickers)
    os.makedirs(DELTA_REPORTS_DIR, exist_ok=True)
    path = os.path.join(DELTA_REPORTS_DIR, "index.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"\n[report index] {path}")


def main():
    parser = argparse.ArgumentParser(description="FinDocQA Delta — filing change intelligence engine.")
    parser.add_argument("ticker", nargs="?", help="Ticker symbol (e.g. AAPL). Use --all for all tickers.")
    parser.add_argument("--years", type=int, default=DELTA_YEARS_DEFAULT, help=f"Number of past years (default: {DELTA_YEARS_DEFAULT}, max: {DELTA_YEARS_MAX}).")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM interpretation (diff only).")
    parser.add_argument("--tickers", type=str, default="", help="Comma-separated tickers for --all mode (default: all 7).")
    parser.add_argument("--all", action="store_true", help="Run pipeline for all tickers.")
    args = parser.parse_args()

    if args.all:
        selected = list(TICKERS.keys())
        if args.tickers:
            selected = [t.strip().upper() for t in args.tickers.split(",") if t.strip() and t.strip().upper() in TICKERS]
    elif args.ticker:
        t = args.ticker.upper()
        if t not in TICKERS:
            print(f"[error] unknown ticker: {args.ticker}")
            sys.exit(1)
        selected = [t]
    else:
        parser.print_help()
        sys.exit(1)

    years = min(args.years, DELTA_YEARS_MAX)

    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")

    for ticker in selected:
        run_delta(ticker, years, no_llm=args.no_llm)

    if len(selected) > 1:
        _write_report_index(selected)


if __name__ == "__main__":
    main()
