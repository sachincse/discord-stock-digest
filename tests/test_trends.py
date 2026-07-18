from datetime import date
from pathlib import Path

from src import ingest, pipeline
from src.config import Config
from src.extract import HeuristicExtractor
from src.gazetteer import Gazetteer
from src.market import StubMarketProvider
from src.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    c = Config()
    c.trusted_users = {"Rajesh": 3.0, "Priya": 2.5, "Vikram": 2.0}
    c.trusted_threshold = 2.0
    return c


def _run(store, report_date, now):
    messages = ingest.load_messages_from_json(ROOT / "data" / "sample_messages.json")
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    return pipeline.run(
        messages, _cfg(), gazetteer=gz, extractor=HeuristicExtractor(),
        market_provider=StubMarketProvider(), store=store,
        now=now, report_date=report_date,
    )


def test_first_day_all_new_then_momentum():
    store = Store(":memory:")
    now = None
    # Day 1: nothing in history -> everything is new
    d1 = _run(store, date(2026, 7, 16), now=_latest())
    assert d1.items
    assert all(it.is_new for it in d1.items)

    # Day 2: same chat again -> seen before, momentum computed
    d2 = _run(store, date(2026, 7, 17), now=_latest())
    rel = _find(d2, "RELIANCE.NS")
    assert not rel.is_new
    assert rel.mention_momentum > 0
    assert rel.baseline_mentions > 0


def test_persistence_survives_new_store_instance(tmp_path):
    db = tmp_path / "digest.db"
    s1 = Store(str(db))
    _run(s1, date(2026, 7, 16), now=_latest())
    s1.close()

    # reopen: history is still there
    s2 = Store(str(db))
    hist = s2.history("RELIANCE.NS")
    s2.close()
    assert hist and hist[0]["report_date"] == "2026-07-16"


def _latest():
    msgs = ingest.load_messages_from_json(ROOT / "data" / "sample_messages.json")
    return max(m.timestamp for m in msgs)


def _find(digest, symbol):
    hits = [i for i in digest.items if i.canonical_symbol == symbol]
    assert hits, f"{symbol} not surfaced"
    return hits[0]
