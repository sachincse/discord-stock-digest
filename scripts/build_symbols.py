#!/usr/bin/env python3
"""Regenerate data/symbols.csv with the full NSE equity universe.

The bundled gazetteer is a curated starter list. Run this to expand it to all
~2,000 NSE-listed companies (plus the indices and US mega-caps we always keep),
so fewer real mentions are missed.

    python scripts/build_symbols.py                 # write data/symbols.csv
    python scripts/build_symbols.py --out my.csv    # write elsewhere

Source: NSE's public EQUITY_L.csv archive (no key). It is an unofficial
endpoint — run occasionally and cache the result; do not fetch every run.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

EQUITY_L = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
}

# Always-keep rows (indices + a few US mega-caps) merged on top of NSE equities.
KEEP = [
    ("^NSEI", "Nifty 50", "NSE", "Nifty|Nifty50|Nifty 50"),
    ("^NSEBANK", "Nifty Bank", "NSE", "BankNifty|Bank Nifty|Nifty Bank"),
    ("^BSESN", "BSE Sensex", "NSE", "Sensex"),
    ("AAPL", "Apple", "US", "Apple"),
    ("MSFT", "Microsoft", "US", "Microsoft"),
    ("GOOGL", "Alphabet", "US", "Google|Alphabet"),
    ("AMZN", "Amazon", "US", "Amazon"),
    ("NVDA", "NVIDIA", "US", "Nvidia"),
    ("META", "Meta Platforms", "US", "Meta|Facebook"),
    ("TSLA", "Tesla", "US", "Tesla"),
]

_STRIP = (" Limited", " Ltd.", " Ltd", " Corporation", " Corp.", " Company")


def _clean(name: str) -> str:
    for s in _STRIP:
        if name.endswith(s):
            name = name[: -len(s)]
    return name.strip()


def build(out_path: Path) -> int:
    try:
        import requests
    except ImportError:
        print("This script needs `requests`: pip install requests", file=sys.stderr)
        return 1

    print(f"Fetching NSE equity list from {EQUITY_L} ...")
    try:
        resp = requests.get(EQUITY_L, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"Download failed ({exc}). NSE endpoints are unofficial and may "
              f"block by IP/region — try again later or from a different network.",
              file=sys.stderr)
        return 1

    reader = csv.DictReader(io.StringIO(resp.text))
    rows: list[tuple[str, str, str, str]] = list(KEEP)
    seen = {r[0] for r in rows}
    n = 0
    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip()
        name = _clean((row.get("NAME OF COMPANY") or "").strip())
        if not symbol or not name:
            continue
        canonical = f"{symbol}.NS"
        if canonical in seen:
            continue
        seen.add(canonical)
        # aliases: full cleaned name + the raw symbol as an acronym
        rows.append((canonical, name, "NSE", f"{name}|{symbol}"))
        n += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["canonical_symbol", "company", "exchange", "aliases"])
        w.writerows(rows)
    print(f"Wrote {len(rows)} symbols ({n} from NSE) to {out_path}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "data" / "symbols.csv"),
    )
    args = p.parse_args(argv)
    return build(Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
