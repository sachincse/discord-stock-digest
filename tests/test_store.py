from datetime import date, datetime, timezone

from src.models import DailyDigest, RawMessage, StockDigestItem
from src.store import Store, enrich_trends


def _msg(i, content="RIL strong"):
    return RawMessage(
        id=str(i), author_id="u1", author_name="A",
        timestamp=datetime(2026, 7, 17, 9, i % 60, tzinfo=timezone.utc),
        content=content,
    )


def _digest(d: date, symbol="RELIANCE.NS", mentions=5):
    item = StockDigestItem(
        canonical_symbol=symbol, company="Reliance", exchange="NSE",
        mention_count=mentions, distinct_authors=3, net_sentiment=0.8,
        weighted_score=4.2, relevance_score=1.0, breaking_news_score=0.5,
        consensus_recommendation="buy",
    )
    return DailyDigest(
        report_date=d, channel_name="stocks",
        generated_at=datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
        total_messages=27, analyzed_messages=20, items=[item], extractor="heuristic",
    )


def test_message_upsert_is_idempotent():
    s = Store(":memory:")
    assert s.save_messages([_msg(1), _msg(2)]) == 2
    # re-inserting the same ids adds nothing
    assert s.save_messages([_msg(1), _msg(2), _msg(3)]) == 1
    cur = s.conn.execute("SELECT COUNT(*) AS n FROM messages")
    assert cur.fetchone()["n"] == 3


def test_baseline_and_is_new():
    s = Store(":memory:")
    today = date(2026, 7, 17)
    # nothing stored yet -> new, zero baseline
    baseline, is_new = s.baseline("RELIANCE.NS", today, days=7)
    assert is_new and baseline == 0.0

    # store three prior days of 6 mentions each
    for d in (date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16)):
        s.save_digest(_digest(d, mentions=6))

    baseline, is_new = s.baseline("RELIANCE.NS", today, days=7)
    assert not is_new
    # 18 mentions over a 7-day window
    assert abs(baseline - 18 / 7) < 1e-6


def test_enrich_trends_sets_momentum():
    s = Store(":memory:")
    today = date(2026, 7, 17)
    for d in (date(2026, 7, 15), date(2026, 7, 16)):
        s.save_digest(_digest(d, mentions=2))  # baseline 4/7 ≈ 0.57/day

    item = StockDigestItem(
        canonical_symbol="RELIANCE.NS", company="Reliance", exchange="NSE",
        mention_count=6,
    )
    enrich_trends([item], s, today, days=7)
    assert not item.is_new
    assert item.baseline_mentions > 0
    assert item.mention_momentum > 1.0  # 6 today vs ~0.57 baseline -> trending

    # a symbol never seen before is flagged new
    fresh = StockDigestItem(canonical_symbol="TCS.NS", company="TCS", exchange="NSE", mention_count=3)
    enrich_trends([fresh], s, today, days=7)
    assert fresh.is_new


def test_save_digest_roundtrips_history():
    s = Store(":memory:")
    s.save_digest(_digest(date(2026, 7, 16), mentions=4))
    s.save_digest(_digest(date(2026, 7, 17), mentions=9))
    hist = s.history("RELIANCE.NS")
    assert len(hist) == 2
    assert hist[0]["report_date"] == "2026-07-17"  # newest first
    assert hist[0]["mention_count"] == 9


def test_already_ran():
    s = Store(":memory:")
    assert not s.already_ran(date(2026, 7, 17))
    s.save_digest(_digest(date(2026, 7, 17)))
    assert s.already_ran(date(2026, 7, 17))
