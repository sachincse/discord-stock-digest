from datetime import datetime, timedelta, timezone

from src.disentangle import build_threads
from src.models import RawMessage

T0 = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)


def _m(i, author, content, minutes, reply_to=None, mentions=None):
    return RawMessage(
        id=str(i),
        author_id=author,
        author_name=author,
        timestamp=T0 + timedelta(minutes=minutes),
        content=content,
        reply_to_id=reply_to,
        mentions=mentions or [],
    )


def test_reply_edges_group_together():
    msgs = [
        _m(1, "A", "What about Reliance?", 0),
        _m(2, "B", "Reliance is strong", 1, reply_to="1"),
        _m(3, "C", "Totally unrelated topic about weather", 30),
    ]
    threads = build_threads(msgs)
    ids = {t.thread_id: {m.id for m in t.messages} for t in threads}
    # messages 1 and 2 share a thread; 3 is separate
    groups = [frozenset(v) for v in ids.values()]
    assert frozenset({"1", "2"}) in groups
    assert frozenset({"3"}) in groups


def test_shared_ticker_within_window_links():
    from pathlib import Path

    from src.gazetteer import Gazetteer

    gz = Gazetteer.load(Path(__file__).resolve().parents[1] / "data" / "symbols.csv")
    msgs = [
        _m(1, "A", "TCS results look good", 0),
        _m(2, "B", "yes TCS margins improving", 3),
    ]
    threads = build_threads(msgs, gz)
    assert len(threads) == 1


def test_mention_links_to_prior_author_message():
    msgs = [
        _m(1, "Alice", "I like Infosys", 0),
        _m(2, "Bob", "hey Alice what price?", 2, mentions=["Alice"]),
    ]
    threads = build_threads(msgs)
    assert len(threads) == 1
