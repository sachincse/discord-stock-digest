"""Stage 5+6 — aggregate mentions per stock, then dual-track rank.

Trust weighting and all scoring live HERE (deterministic), never inside the
LLM. Ranking uses two independent tracks so we surface investment-relevant
consensus WITHOUT missing big news from unknown users:

  * Track A  relevance  — trust-weighted consensus (who + how many + how
                          strongly + how substantive).
  * Track B  breaking   — weight-agnostic burst: events, volume/news spikes,
                          mention velocity. A low-trust user breaking real
                          news still gets surfaced.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from .config import Config
from .models import (
    Evidence,
    MarketSnapshot,
    SENTIMENT_VALUE,
    StockDigestItem,
    StockMention,
    TrustedStance,
)


def _recency_weight(ts: datetime, now: datetime, half_life_h: float) -> float:
    age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
    return 0.5 ** (age_h / max(half_life_h, 0.1))


def build_items(
    mentions: list[StockMention],
    market: dict[str, MarketSnapshot] | None,
    config: Config,
    now: datetime | None = None,
) -> list[StockDigestItem]:
    now = now or datetime.now(timezone.utc)
    market = market or {}
    groups: dict[str, list[StockMention]] = defaultdict(list)
    for m in mentions:
        groups[m.canonical_symbol].append(m)

    items: list[StockDigestItem] = []
    for symbol, group in groups.items():
        item = StockDigestItem(
            canonical_symbol=symbol,
            company=group[0].company,
            exchange=group[0].exchange,
            mention_count=len(group),
            market=market.get(symbol),
        )

        authors = set()
        wsum = 0.0
        sent_num = 0.0
        sent_den = 0.0
        rec_weights: dict[str, float] = defaultdict(float)
        events: set[str] = set()
        trusted: dict[str, TrustedStance] = {}
        point_types: set[str] = set()

        for m in group:
            w = config.weight_for(m.author_name, m.author_id)
            rw = _recency_weight(m.timestamp, now, config.recency_half_life_hours)
            # List-spam guard: a "my picks: A B C D E" watchlist dump splits its
            # weight across all tickers named, so scattergun posts can't dominate.
            eff = w * rw / max(1, m.tickers_in_message)
            wsum += eff
            authors.add(m.author_id)

            sv = SENTIMENT_VALUE.get(m.sentiment, 0.0)
            sent_num += eff * sv
            sent_den += eff

            if m.recommendation and m.recommendation != "unclear":
                rec_weights[m.recommendation] += eff

            events.update(m.event_flags)
            point_types.update(k for k, v in m.points.items() if v)

            if m.evidence_quote:
                ev = Evidence(m.evidence_quote, m.author_name, m.message_id, w)
                if m.sentiment == "positive":
                    item.positives.append(f"{m.author_name}: {m.evidence_quote}")
                elif m.sentiment == "negative":
                    item.negatives.append(f"{m.author_name}: {m.evidence_quote}")
                item.evidence.append(ev)

            for _k, v in m.points.items():
                if v and v not in item.key_points:
                    item.key_points.append(v)

            if w >= config.trusted_threshold:
                trusted[m.author_name] = TrustedStance(
                    author_name=m.author_name,
                    weight=w,
                    sentiment=m.sentiment,
                    recommendation=m.recommendation,
                    quote=m.evidence_quote,
                )

        item.distinct_authors = len(authors)
        item.weighted_score = round(wsum, 3)
        item.net_sentiment = (round(sent_num / sent_den, 3) or 0.0) if sent_den else 0.0
        item.consensus_recommendation = (
            max(rec_weights.items(), key=lambda kv: kv[1])[0] if rec_weights else "unclear"
        )
        item.event_flags = sorted(events)
        item.trusted_stances = list(trusted.values())
        # Trim evidence lists to the most useful few.
        item.positives = _top(item.positives, 3)
        item.negatives = _top(item.negatives, 3)
        item.key_points = _top(item.key_points, 4)
        item._point_richness = len(point_types)  # type: ignore[attr-defined]
        items.append(item)

    return items


def rank(items: list[StockDigestItem], config: Config) -> list[StockDigestItem]:
    if not items:
        return []
    max_w = max((i.weighted_score for i in items), default=1.0) or 1.0
    max_m = max((i.mention_count for i in items), default=1) or 1

    for item in items:
        pr = getattr(item, "_point_richness", 0)
        mom = 1.0 if item.mention_momentum >= config.momentum_threshold else 0.0
        breadth = 1 + 0.3 * math.log1p(item.distinct_authors)
        conviction = 0.5 + 0.5 * abs(item.net_sentiment)
        substance = 1 + 0.15 * pr
        trend = 1 + 0.20 * mom  # cross-day momentum lifts relevance
        rel = (item.weighted_score / max_w) * breadth * conviction * substance * trend
        item.relevance_score = round(rel, 4)

        # Weight-agnostic: a concrete event (order win, results, circuit, SEBI
        # action...) alone crosses the default threshold, so real news from an
        # unknown/low-trust user is never dropped. Cross-day momentum, market
        # volume and news spikes stack on top.
        has_event = 1.0 if item.event_flags else 0.0
        vol_spike = 0.0
        news_spike = 0.0
        if item.market:
            if item.market.volume_ratio and item.market.volume_ratio >= 2.0:
                vol_spike = 1.0
            if item.market.news_count >= 5:
                news_spike = 1.0
        burst = item.mention_count / max_m
        bn = (0.60 * has_event + 0.40 * mom + 0.18 * vol_spike
              + 0.12 * news_spike + 0.12 * burst)
        item.breaking_news_score = round(min(bn, 1.0), 4)

    # Normalise relevance to 0..1 for display comparability.
    max_rel = max((i.relevance_score for i in items), default=1.0) or 1.0
    for item in items:
        item.relevance_score = round(item.relevance_score / max_rel, 4)

    ranked = sorted(items, key=lambda i: i.relevance_score, reverse=True)
    top = set(id(i) for i in ranked[: config.top_n])

    surfaced: list[StockDigestItem] = []
    for item in ranked:
        in_top = id(item) in top
        is_breaking = item.breaking_news_score >= config.breaking_news_threshold
        if in_top and is_breaking:
            reason = "top consensus + breaking news"
        elif in_top:
            reason = "top consensus"
        elif is_breaking:
            reason = "breaking news (velocity/event)"
        else:
            continue
        if item.is_new:
            reason += " · 🆕 new today"
        elif item.mention_momentum >= config.momentum_threshold:
            reason += f" · 📈 trending ({item.mention_momentum:.1f}× baseline)"
        item.surfaced_reason = reason
        surfaced.append(item)

    surfaced.sort(
        key=lambda i: max(i.relevance_score, i.breaking_news_score), reverse=True
    )
    return surfaced


def _top(items: list[str], n: int) -> list[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
        if len(out) >= n:
            break
    return out
