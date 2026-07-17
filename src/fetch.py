"""
Fetch raw inputs from SEC EDGAR: companyfacts JSON + the 10-K HTML doc.
Raw layer (plan sec 2): cache forever, never re-fetch. Filings are immutable.
"""
import argparse
import json
import time
import os
import requests
from config import TICKERS, TICKER_10K_OFFSET, USER_AGENT, SEC_RATE_LIMIT, RAW_DIR, DELTA_YEARS_DEFAULT, DELTA_YEARS_MAX

HEADERS = {"User-Agent": USER_AGENT}
MIN_INTERVAL = 1.0 / SEC_RATE_LIMIT
_last_call = [0.0]


def _throttled_get(url, retries=3):
    for attempt in range(retries):
        elapsed = time.time() - _last_call[0]
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as e:
            _last_call[0] = time.time()
            if attempt == retries - 1:
                raise RuntimeError(f"SEC request failed after {retries} attempts. URL: {url}") from e
            time.sleep(2 ** attempt)
            continue
        _last_call[0] = time.time()
        if resp.status_code == 403:
            raise RuntimeError(f"403 from SEC — check User-Agent header. URL: {url}")
        if resp.status_code == 429:
            if attempt == retries - 1:
                raise RuntimeError(f"429 rate limit exceeded. URL: {url}")
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Failed after {retries} retries. URL: {url}")


def fetch_companyfacts(ticker, cik):
    path = f"{RAW_DIR}/{ticker}_companyfacts.json"
    if os.path.exists(path):
        print(f"[skip] {ticker} companyfacts cached")
        return path
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    data = _throttled_get(url).json()
    with open(path, "w") as f:
        json.dump(data, f)
    print(f"[fetched] {ticker} companyfacts")
    return path


def find_latest_10k(ticker, cik, offset=0):
    """Returns (accession_no, primary_doc_filename, period_end, entity_name) for the Nth most recent 10-K."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = _throttled_get(url).json()
    recent = data["filings"]["recent"]
    ten_k_indices = [i for i, form in enumerate(recent["form"]) if form == "10-K"]
    if offset >= len(ten_k_indices):
        raise ValueError(
            f"Not enough 10-Ks for {ticker}: requested offset {offset}, found {len(ten_k_indices)}"
        )
    i = ten_k_indices[offset]
    return (
        recent["accessionNumber"][i].replace("-", ""),
        recent["primaryDocument"][i],
        recent["reportDate"][i],
        data.get("name", ""),
    )


def fetch_10k_html(ticker, cik, offset=0):
    path = f"{RAW_DIR}/{ticker}_10k.html"
    meta_path = f"{RAW_DIR}/{ticker}_10k_meta.json"
    if os.path.exists(path) and os.path.exists(meta_path):
        print(f"[skip] {ticker} 10-K cached")
        with open(meta_path) as f:
            return path, json.load(f)

    accession_no, doc_filename, period_end, entity_name = find_latest_10k(ticker, cik, offset)
    cik_int = str(int(cik))  # SEC drops leading zeros in this URL pattern
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no}/{doc_filename}"
    html = _throttled_get(url).text

    with open(path, "w") as f:
        f.write(html)
    meta = {
        "accession_no": accession_no,
        "doc_filename": doc_filename,
        "period_end": period_end,
        "entity_name": entity_name,
        "url": url,
        "offset": offset,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"[fetched] {ticker} ({entity_name}) 10-K, offset={offset}, period_end={period_end}")
    return path, meta


def fiscal_year_label(period_end: str) -> str:
    """Extract the 4-digit fiscal year from a period_end date string.

    Returns 'FY{year}' where year is the year the fiscal period ENDS in.
    Example: '2025-09-27' -> 'FY2025', '2025-01-25' -> 'FY2025'.
    """
    year = period_end[:4]
    return f"FY{year}"


def find_n_recent_10ks(ticker, cik, n):
    """Return list of dicts for the N most recent 10-Ks from submissions API.

    Each dict: {accession_no, doc_filename, period_end, entity_name, fiscal_year}.
    Filters form == '10-K'. Takes first N. Returns fewer if N are not available.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = _throttled_get(url).json()
    recent = data["filings"]["recent"]
    entity_name = data.get("name", "")
    ten_k_indices = [i for i, form in enumerate(recent["form"]) if form == "10-K"]
    results = []
    for i in ten_k_indices[:n]:
        period_end = recent["reportDate"][i]
        results.append({
            "accession_no": recent["accessionNumber"][i].replace("-", ""),
            "doc_filename": recent["primaryDocument"][i],
            "period_end": period_end,
            "entity_name": entity_name,
            "fiscal_year": fiscal_year_label(period_end),
        })
    if len(results) < n:
        print(f"[warn] {ticker}: only {len(results)} 10-Ks available, requested {n}")
    return results


def fetch_10k_html_for_year(ticker, cik, accession_no, doc_filename, period_end, entity_name, fiscal_year):
    """Fetch and cache a specific 10-K with year-suffixed naming.

    Returns (path, meta). Skips if cached.
    """
    fy = fiscal_year
    path = f"{RAW_DIR}/{ticker}_{fy}_10k.html"
    meta_path = f"{RAW_DIR}/{ticker}_{fy}_10k_meta.json"
    if os.path.exists(path) and os.path.exists(meta_path):
        print(f"[skip] {ticker} {fy} 10-K cached")
        with open(meta_path) as f:
            return path, json.load(f)

    cik_int = str(int(cik))
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no}/{doc_filename}"
    html = _throttled_get(url).text

    with open(path, "w") as f:
        f.write(html)
    meta = {
        "accession_no": accession_no,
        "doc_filename": doc_filename,
        "period_end": period_end,
        "entity_name": entity_name,
        "url": url,
        "fiscal_year": fy,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"[fetched] {ticker} ({entity_name}) {fy} 10-K, period_end={period_end}")
    return path, meta


def fetch_all_for_delta(tickers, years):
    """Fetch N years of 10-Ks for each ticker. Skips cached filings."""
    for ticker, cik in tickers.items():
        fetch_companyfacts(ticker, cik)
        records = find_n_recent_10ks(ticker, cik, years)
        for rec in records:
            fetch_10k_html_for_year(
                ticker, cik,
                rec["accession_no"], rec["doc_filename"],
                rec["period_end"], rec["entity_name"], rec["fiscal_year"],
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch 10-K filings from SEC EDGAR.")
    parser.add_argument("--years", type=int, default=1, help=f"Number of past 10-Ks per ticker (default: 1, max: {DELTA_YEARS_MAX}).")
    parser.add_argument("--tickers", type=str, default="", help="Comma-separated tickers (default: all).")
    args = parser.parse_args()

    years = min(args.years, DELTA_YEARS_MAX)
    selected = dict(TICKERS)
    if args.tickers:
        names = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        selected = {t: cik for t, cik in TICKERS.items() if t in names}

    os.makedirs(RAW_DIR, exist_ok=True)

    if years > 1:
        fetch_all_for_delta(selected, years)
    else:
        for ticker, cik in selected.items():
            fetch_companyfacts(ticker, cik)
            fetch_10k_html(ticker, cik, offset=TICKER_10K_OFFSET.get(ticker, 0))
