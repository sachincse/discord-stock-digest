from datetime import datetime, timezone

from src.aggregate import build_items, rank
from src.config import Config
from src.models import StockMention

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _mention(symbol, author, weight_name, sentiment, rec, events=None, mid="m"):
    return StockMention(
        canonical_symbol=symbol,
        company=symbol,
        exchange="NSE",
        ticker_raw=symbol,
        author_id=author,
        author_name=weight_name,
        timestamp=NOW,
        thread_id="t0",
        message_id=mid,
        sentiment=sentiment,
        recommendation=rec,
        evidence_quote=f"{weight_name} on {symbol}",
        event_flags=events or [],
    )


def _config():
    c = Config()
    c.trusted_users = {"Rajesh": 3.0, "Priya": 2.5}
    c.trusted_threshold = 2.0
    c.top_n = 5
    return c


def test_weighting_and_sentiment():
    config = _config()
    mentions = [
        _mention("RELIANCE.NS", "u1", "Rajesh", "positive", "buy", mid="1"),
        _mention("RELIANCE.NS", "u2", "Priya", "positive", "buy", mid="2"),
        _mention("RELIANCE.NS", "u3", "Amit", "negative", "sell", mid="3"),
    ]
    items = build_items(mentions, {}, config, now=NOW)
    item = items[0]
    assert item.canonical_symbol == "RELIANCE.NS"
    assert item.distinct_authors == 3
    # trusted bullish weight (3.0 + 2.5) outweighs one bearish (1.0)
    assert item.net_sentiment > 0
    assert item.consensus_recommendation == "buy"
    assert len(item.trusted_stances) == 2


def test_breaking_news_surfaces_low_trust_event():
    config = _config()
    mentions = [
        # low-trust user, but a concrete event -> breaking-news track
        _mention("RVNL.NS", "u6", "NoobTrader", "positive", "unclear", events=["order"], mid="1"),
    ]
    items = build_items(mentions, {}, config, now=NOW)
    ranked = rank(items, config)
    rvnl = [i for i in ranked if i.canonical_symbol == "RVNL.NS"]
    assert rvnl, "event-carrying mention should be surfaced"
    assert rvnl[0].breaking_news_score >= config.breaking_news_threshold
    assert "breaking" in rvnl[0].surfaced_reason


def test_rank_orders_by_relevance():
    config = _config()
    mentions = [
        _mention("RELIANCE.NS", "u1", "Rajesh", "positive", "buy", mid="1"),
        _mention("RELIANCE.NS", "u2", "Priya", "positive", "buy", mid="2"),
        _mention("ZOMATO.NS", "u3", "Amit", "negative", "avoid", mid="3"),
    ]
    ranked = rank(build_items(mentions, {}, config, now=NOW), config)
    assert ranked[0].canonical_symbol == "RELIANCE.NS"
