"""
Fetch raw inputs from SEC EDGAR: companyfacts JSON + the 10-K HTML doc.
Raw layer (plan sec 2): cache forever, never re-fetch. Filings are immutable.
"""
import json
import time
import os
import requests
from config import TICKERS, USER_AGENT, SEC_RATE_LIMIT, RAW_DIR

HEADERS = {"User-Agent": USER_AGENT}
MIN_INTERVAL = 1.0 / SEC_RATE_LIMIT
_last_call = [0.0]


def _throttled_get(url):
    elapsed = time.time() - _last_call[0]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    resp = requests.get(url, headers=HEADERS)
    _last_call[0] = time.time()
    if resp.status_code == 403:
        raise RuntimeError(f"403 from SEC — check User-Agent header. URL: {url}")
    resp.raise_for_status()
    return resp


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


def find_latest_10k(ticker, cik):
    """Returns (accession_no, primary_doc_filename, period_end)."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = _throttled_get(url).json()
    recent = data["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return (
                recent["accessionNumber"][i].replace("-", ""),
                recent["primaryDocument"][i],
                recent["reportDate"][i],
            )
    raise ValueError(f"No 10-K found for {ticker}")


def fetch_10k_html(ticker, cik):
    path = f"{RAW_DIR}/{ticker}_10k.html"
    meta_path = f"{RAW_DIR}/{ticker}_10k_meta.json"
    if os.path.exists(path):
        print(f"[skip] {ticker} 10-K cached")
        with open(meta_path) as f:
            return path, json.load(f)

    accession_no, doc_filename, period_end = find_latest_10k(ticker, cik)
    cik_int = str(int(cik))  # SEC drops leading zeros in this URL pattern
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no}/{doc_filename}"
    html = _throttled_get(url).text

    with open(path, "w") as f:
        f.write(html)
    meta = {"accession_no": accession_no, "doc_filename": doc_filename, "period_end": period_end, "url": url}
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"[fetched] {ticker} 10-K, period_end={period_end}")
    return path, meta


if __name__ == "__main__":
    os.makedirs(RAW_DIR, exist_ok=True)
    for ticker, cik in TICKERS.items():
        fetch_companyfacts(ticker, cik)
        fetch_10k_html(ticker, cik)