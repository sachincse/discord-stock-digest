#!/usr/bin/env python3
"""discord-stock-digest — CLI entrypoint.

Examples
--------
Offline demo (no keys, uses bundled sample chat + stub market data):
    python main.py --selftest

Analyse an exported JSON file with a chosen extractor + persist to SQLite:
    python main.py --from-json data/export.json --backend ollama --live-market

Live run against Discord (needs DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID):
    python main.py --once --backend gemini

Show a stock's stored day-by-day history:
    python main.py --history RELIANCE.NS

Run every day at a fixed time:
    python main.py --schedule --at 21:30
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# Windows consoles default to cp1252; the report uses ·, —, and emoji.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from src import ingest, pipeline, report
from src.config import Config
from src.gazetteer import Gazetteer
from src.market import StubMarketProvider, select_provider
from src.store import Store

ROOT = Path(__file__).parent
SAMPLE = ROOT / "data" / "sample_messages.json"


def _print_summary(digest, paths):
    print("\n" + "=" * 60)
    print(f"  Digest for #{digest.channel_name} — {digest.report_date}")
    print(f"  {digest.analyzed_messages}/{digest.total_messages} messages analysed"
          f" · extractor={digest.extractor}")
    print("=" * 60)
    if not digest.items:
        print("  (no stocks surfaced)")
    for i, it in enumerate(digest.items, 1):
        print(f"  {i:>2}. {it.company:<28} {it.canonical_symbol:<12} "
              f"{it.consensus_recommendation.upper():<11} "
              f"sent={it.net_sentiment:+.2f} rel={it.relevance_score:.2f} "
              f"news={it.breaking_news_score:.2f} — {it.surfaced_reason}")
    print("=" * 60)
    for kind, p in (paths or {}).items():
        print(f"  {kind}: {p}")
    print()


def _make_store(config: Config, args) -> Store | None:
    if getattr(args, "no_db", False) or not config.use_db:
        return None
    return Store(args.db or config.db_path)


def _report_date(args) -> date | None:
    if getattr(args, "date", None):
        return date.fromisoformat(args.date)
    return None


def cmd_selftest(config: Config) -> int:
    print("[selftest] running fully offline (heuristic extractor + stub market)")
    from src.extract import HeuristicExtractor

    # Use the example config so the demo showcases trust weighting even when
    # the user hasn't created their own config.yaml yet.
    if not config.trusted_users and (ROOT / "config.example.yaml").exists():
        config = Config.load(ROOT / "config.example.yaml")

    messages = ingest.load_messages_from_json(SAMPLE)
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    digest = pipeline.run(
        messages,
        config,
        gazetteer=gz,
        extractor=HeuristicExtractor(),
        market_provider=StubMarketProvider(),
        now=messages and _latest(messages) or datetime.now(timezone.utc),
    )
    paths = report.deliver(digest, config)
    _print_summary(digest, paths)
    assert digest.items, "selftest expected at least one surfaced stock"
    print("[selftest] OK")
    return 0


def cmd_from_json(config: Config, path: str, args) -> int:
    messages = ingest.load_messages_from_json(path)
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    provider = select_provider(config.use_market_data, args.live_market)
    store = _make_store(config, args)
    try:
        digest = pipeline.run(
            messages, config, gazetteer=gz, market_provider=provider,
            store=store, report_date=_report_date(args),
        )
    finally:
        if store:
            store.close()
    paths = report.deliver(digest, config)
    _print_summary(digest, paths)
    return 0


def cmd_once(config: Config, args) -> int:
    from src import discord_bot

    print(f"[once] fetching last {config.lookback_hours}h from channel {config.channel_id}")
    messages = discord_bot.fetch_messages(config)
    print(f"[once] fetched {len(messages)} messages")
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    provider = select_provider(config.use_market_data, args.live_market)
    store = _make_store(config, args)
    try:
        digest = pipeline.run(
            messages, config, gazetteer=gz, market_provider=provider,
            store=store, report_date=_report_date(args),
        )
    finally:
        if store:
            store.close()
    paths = report.deliver(digest, config)
    _print_summary(digest, paths)
    return 0


def cmd_history(config: Config, symbol: str, args) -> int:
    store = _make_store(config, args)
    if store is None:
        print("[history] database is disabled")
        return 1
    try:
        rows = store.history(symbol, limit=30)
    finally:
        store.close()
    if not rows:
        print(f"[history] no stored data for {symbol} in {args.db or config.db_path}")
        return 0
    print(f"\n  Day-by-day history for {symbol}")
    print("  " + "-" * 52)
    print(f"  {'date':<12}{'mentions':>10}{'sentiment':>12}{'relevance':>12}")
    for r in reversed(rows):  # oldest first
        print(f"  {r['report_date']:<12}{r['mention_count']:>10}"
              f"{r['net_sentiment']:>12.2f}{r['relevance_score']:>12.2f}")
    print()
    return 0


def cmd_schedule(config: Config, args) -> int:
    hh, mm = (int(x) for x in args.at.split(":"))
    print(f"[schedule] will run daily at {args.at} local time. Ctrl-C to stop.")
    last_run = None
    while True:
        now = datetime.now()
        if now.hour == hh and now.minute == mm and last_run != now.date():
            try:
                cmd_once(config, args)
            except Exception as exc:  # keep the scheduler alive
                print(f"[schedule] run failed: {exc}")
            last_run = now.date()
        time.sleep(30)


def _latest(messages):
    return max(m.timestamp for m in messages)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Daily stock-chat digest from a Discord channel")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--selftest", action="store_true", help="offline demo with bundled data")
    g.add_argument("--from-json", metavar="PATH", help="analyse an exported JSON file")
    g.add_argument("--once", action="store_true", help="one live run against Discord")
    g.add_argument("--schedule", action="store_true", help="run daily (see --at)")
    g.add_argument("--history", metavar="SYMBOL", help="print stored day-by-day history")
    p.add_argument("--backend", choices=["auto", "heuristic", "gemini", "ollama"],
                   help="which extractor to use (overrides config)")
    p.add_argument("--at", default="21:30", help="HH:MM local time for --schedule")
    p.add_argument("--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="report date override (backfills)")
    p.add_argument("--db", metavar="PATH", help="SQLite path (overrides config)")
    p.add_argument("--no-db", action="store_true", help="disable SQLite persistence")
    p.add_argument("--live-market", action="store_true", help="use real yfinance data")
    p.add_argument("--no-market", action="store_true", help="disable market data")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(args.config)
    if args.no_market:
        config.use_market_data = False
    if args.backend:
        config.extractor_backend = args.backend

    if args.from_json:
        return cmd_from_json(config, args.from_json, args)
    if args.once:
        return cmd_once(config, args)
    if args.history:
        return cmd_history(config, args.history, args)
    if args.schedule:
        return cmd_schedule(config, args)
    # default: selftest (safe, no secrets required)
    return cmd_selftest(config)


if __name__ == "__main__":
    sys.exit(main())
