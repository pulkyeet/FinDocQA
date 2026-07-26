"""Re-render Delta report HTML from persisted pipeline output.

Stage 7 (interpretation) is the expensive one — hundreds of LLM calls per
ticker — and its output is persisted. This script rebuilds the report from that
output after a template, CSS, or report.py change.

By default it reuses the persisted narrative too, so a pure styling change costs
no LLM calls at all. --narrate recomposes the chapter prose (roughly six calls
per ticker), which is what you want after editing the narrative prompts.

Usage:
  python rerender.py                      # all tickers, no LLM
  python rerender.py MSFT AAPL            # specific tickers
  python rerender.py AAPL --narrate       # recompose prose, then render
  python rerender.py AAPL --narrate --no-item8 --suffix _variantB
"""

import argparse
import glob
import json
import os

from config import TICKERS, XBRL_DELTA_TAGS, DELTA_DIFFS_DIR, DELTA_REPORTS_DIR
from delta.report import (
    build_report_data, render_html, render_cli_summary, write_report,
    load_interpretations, load_narratives, write_narratives, build_report_index,
)
from delta.xbrl_delta import load_companyfacts, compute_yoy_deltas, build_metric_series

ENTITY_NAMES = {
    "AAPL": "Apple Inc.", "AMZN": "Amazon.com, Inc.", "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.", "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation", "TSLA": "Tesla, Inc.",
}


def load_records_by_year(ticker: str) -> dict:
    """Reconstruct {(y_old, y_new): [diff_records]} from persisted jsonl files."""
    records_by_year = {}
    pattern = os.path.join(DELTA_DIFFS_DIR, ticker, "FY*_FY*.jsonl")
    for path in sorted(glob.glob(pattern)):
        base = os.path.basename(path)[:-6]  # strip ".jsonl"
        y_old, y_new = base.split("_")
        with open(path) as f:
            records_by_year[(y_old, y_new)] = [json.loads(ln) for ln in f if ln.strip()]
    return records_by_year


def rerender(ticker: str, narrate: bool = False, item8: bool = True,
             suffix: str = "", quiet: bool = False) -> bool:
    records_by_year = load_records_by_year(ticker)
    if not records_by_year:
        print(f"[skip] {ticker}: no persisted diff records")
        return False

    interpretations = load_interpretations(ticker)
    fys = sorted({y for yp in records_by_year for y in yp})

    try:
        cf = load_companyfacts(ticker)
        xbrl_deltas = compute_yoy_deltas(cf, XBRL_DELTA_TAGS, fys)
        metric_series = build_metric_series(cf, XBRL_DELTA_TAGS, fys)
    except FileNotFoundError:
        xbrl_deltas, metric_series = {}, {}

    entity = ENTITY_NAMES.get(ticker, ticker)

    if narrate:
        from config import FINANCIALS_NARRATIVE_ANCHORS
        from delta.narrate import narrate_ticker
        print(f"[narrate] {ticker}")
        chapters, exec_summary, financial_narrative = narrate_ticker(
            ticker, entity, interpretations, metric_series, fys,
            financials_anchors=FINANCIALS_NARRATIVE_ANCHORS if item8 else [],
        )
        if not suffix:
            write_narratives(chapters, exec_summary, financial_narrative, ticker)
    else:
        chapters, exec_summary, financial_narrative = load_narratives(ticker)
        if not chapters and not exec_summary:
            print(f"[warn] {ticker}: no persisted narrative — re-run with --narrate")
        if not item8:
            # Reconstruct variant B from the persisted variant-A narrative without
            # burning an LLM call: chapters are anchor-disjoint from Item 8, so
            # only dropping the financial narrative is needed to match what
            # --narrate --no-item8 would have produced.
            financial_narrative = None

    report = build_report_data(
        ticker, records_by_year, interpretations, xbrl_deltas,
        metric_series=metric_series, chapters=chapters,
        exec_summary=exec_summary, financial_narrative=financial_narrative,
        entity_name=entity,
    )
    path = write_report(ticker, render_html(report), suffix=suffix)
    if quiet:
        print(f"[ok] {ticker}: {path}  ({report['read_time']} min read, "
              f"{report['word_count']:,} words)")
    else:
        print(render_cli_summary(report))
        print(f"  -> {path}")
    return True


def main():
    p = argparse.ArgumentParser(description="Re-render Delta reports from persisted output.")
    p.add_argument("tickers", nargs="*", help="Tickers (default: all)")
    p.add_argument("--narrate", action="store_true",
                   help="Recompose chapter prose via LLM before rendering.")
    p.add_argument("--no-item8", action="store_true",
                   help="Variant B: drop the Item 8 / financial-statement narrative.")
    p.add_argument("--suffix", default="",
                   help="Filename suffix, e.g. _variantB (does not overwrite the main report).")
    p.add_argument("--quiet", action="store_true", help="One line per ticker.")
    args = p.parse_args()

    selected = [t.upper() for t in args.tickers] or list(TICKERS.keys())
    for t in selected:
        rerender(t, narrate=args.narrate, item8=not args.no_item8,
                 suffix=args.suffix, quiet=args.quiet)

    have_reports = [t for t in TICKERS
                    if os.path.isfile(os.path.join(DELTA_REPORTS_DIR, f"{t}.html"))]
    if have_reports:
        os.makedirs(DELTA_REPORTS_DIR, exist_ok=True)
        with open(os.path.join(DELTA_REPORTS_DIR, "index.html"), "w") as f:
            f.write(build_report_index(have_reports))
        print(f"\n[index] {len(have_reports)} reports: {', '.join(sorted(have_reports))}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")
    main()
