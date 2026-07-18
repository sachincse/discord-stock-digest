"""End-to-end orchestration: raw messages -> DailyDigest.

    ingest -> noise filter -> disentangle -> extract -> market -> aggregate
           -> rank -> DailyDigest

Every stage is swappable; the pipeline itself is pure and testable (pass in
messages + an extractor + a market provider, get a digest back).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from . import aggregate, disentangle, noise_filter
from .config import Config
from .extract import Extractor, select_extractor
from .gazetteer import Gazetteer
from .market import MarketProvider, select_provider
from .models import DailyDigest, RawMessage
from .store import Store, enrich_trends


def run(
    messages: list[RawMessage],
    config: Config,
    *,
    gazetteer: Gazetteer | None = None,
    extractor: Extractor | None = None,
    market_provider: MarketProvider | None = None,
    store: Store | None = None,
    now: datetime | None = None,
    report_date: date | None = None,
) -> DailyDigest:
    now = now or datetime.now(timezone.utc)
    rdate = report_date or now.date()
    gz = gazetteer or Gazetteer.load()
    extractor = extractor or select_extractor(config)

    # Persist raw messages first (idempotent) — decouples ingest from the LLM
    # step and lets a crashed run resume without re-fetching.
    if store is not None:
        store.save_messages(messages)

    total = len(messages)
    kept, _dropped = noise_filter.filter_messages(messages, gz)
    threads = disentangle.build_threads(kept, gz)
    mentions = extractor.extract(threads, gz, config)

    market = None
    if market_provider is not None:
        symbols = sorted({m.canonical_symbol for m in mentions})
        market = market_provider.fetch(symbols)

    items = aggregate.build_items(mentions, market, config, now)
    # Read cross-day baseline BEFORE saving today's row, so a symbol is never
    # its own baseline; momentum/is_new then feed the ranking.
    enrich_trends(items, store, rdate, config.momentum_baseline_days)
    ranked = aggregate.rank(items, config)

    analyzed = len({m.message_id for m in mentions})
    digest = DailyDigest(
        report_date=rdate,
        channel_name=config.channel_name,
        generated_at=now,
        total_messages=total,
        analyzed_messages=analyzed,
        items=ranked,
        extractor=extractor.name,
    )

    if store is not None:
        store.save_digest(digest)
        store.save_mentions(rdate, mentions)

    return digest
