"""
update_valuation.py — Refresh ONLY the valuation multiples (估值指標) in ticker reports.

Much faster than update_financials.py since it only fetches stock.info (no financial statements).
Updates: P/E (TTM), Forward P/E, P/S, P/B, EV/EBITDA, stock price, and period dates.
Preserves all other content including financial tables.

Usage:
  python scripts/update_valuation.py                     # ALL tickers
  python scripts/update_valuation.py 2330                # Single ticker
  python scripts/update_valuation.py 2330 2317 3034      # Multiple tickers
  python scripts/update_valuation.py --batch 101         # By batch
  python scripts/update_valuation.py --sector Semiconductors  # By sector
  python scripts/update_valuation.py --dry-run 2330      # Preview without writing
"""

import os
import re
import sys
import time

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    find_ticker_files, parse_scope_args, setup_stdout,
    fetch_valuation_data, build_valuation_table, update_metadata,
)


def fetch_valuation(ticker):
    """Fetch valuation multiples only. Tries .TW then .TWO."""
    for suffix in [".TW", ".TWO"]:
        try:
            stock = yf.Ticker(f"{ticker}{suffix}")
            info = stock.info
            if not info or not info.get("currentPrice"):
                continue

            valuation = fetch_valuation_data(info)

            market_cap = (
                f"{info['marketCap'] / 1_000_000:,.0f}"
                if info.get("marketCap")
                else None
            )
            enterprise_value = (
                f"{info['enterpriseValue'] / 1_000_000:,.0f}"
                if info.get("enterpriseValue")
                else None
            )

            return {
                "valuation": valuation,
                "market_cap": market_cap,
                "enterprise_value": enterprise_value,
                "suffix": suffix,
            }
        except Exception:
            continue
    return None


def update_file(filepath, ticker, dry_run=False):
    """Update only the valuation section in a ticker file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    data = fetch_valuation(ticker)
    if data is None:
        print(f"  {ticker}: SKIP (no data)")
        return False

    new_table = build_valuation_table(data["valuation"])

    # Replace existing 估值指標 section (between ### 估值指標 and ### 年度)
    if "### 估值指標" in content:
        content = re.sub(
            r"### 估值指標.*?(?=\n### 年度)",
            new_table + "\n",
            content,
            flags=re.DOTALL,
        )
    elif "## 財務概況" in content:
        # No valuation section yet — insert before 年度
        content = content.replace(
            "### 年度關鍵財務數據",
            new_table + "\n\n### 年度關鍵財務數據",
        )

    content = update_metadata(content, data.get("market_cap"), data.get("enterprise_value"))

    if dry_run:
        print(f"  {ticker}: WOULD UPDATE ({data['suffix']})")
        return True

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  {ticker}: UPDATED ({data['suffix']})")
    return True


def main():
    setup_stdout()

    args = list(sys.argv[1:])
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    tickers, sector, desc = parse_scope_args(args)
    print(f"Updating valuation for {desc}...")
    files = find_ticker_files(tickers, sector)

    if not files:
        print("No matching files found.")
        return

    print(f"Found {len(files)} files.\n")
    updated = failed = skipped = 0

    for ticker in sorted(files.keys()):
        try:
            if update_file(files[ticker], ticker, dry_run):
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  {ticker}: ERROR ({e})")
            failed += 1
        time.sleep(0.3)

    print(f"\nDone. Updated: {updated} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
