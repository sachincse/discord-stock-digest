from datetime import datetime, timezone
from pathlib import Path

from src import ingest, pipeline
from src.config import Config
from src.extract import HeuristicExtractor
from src.gazetteer import Gazetteer
from src.market import StubMarketProvider

ROOT = Path(__file__).resolve().parents[1]


def _run():
    messages = ingest.load_messages_from_json(ROOT / "data" / "sample_messages.json")
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    config = Config()
    config.trusted_users = {"Rajesh": 3.0, "Priya": 2.5, "Vikram": 2.0}
    config.trusted_threshold = 2.0
    now = max(m.timestamp for m in messages)
    return pipeline.run(
        messages,
        config,
        gazetteer=gz,
        extractor=HeuristicExtractor(),
        market_provider=StubMarketProvider(),
        now=now,
    )


def test_pipeline_produces_digest():
    digest = _run()
    assert digest.items, "expected surfaced stocks"
    assert digest.extractor == "heuristic"
    assert digest.total_messages == 27
    # bot + greeting messages were filtered out
    assert digest.analyzed_messages < digest.total_messages


def test_reliance_is_top_consensus():
    digest = _run()
    top = digest.items[0]
    assert top.canonical_symbol == "RELIANCE.NS"
    assert top.consensus_recommendation == "buy"
    assert top.net_sentiment > 0


def test_rvnl_surfaced_as_breaking_news():
    digest = _run()
    rvnl = [i for i in digest.items if i.canonical_symbol == "RVNL.NS"]
    assert rvnl, "RVNL order-win should surface even from a low-trust user"
    assert "breaking" in rvnl[0].surfaced_reason


def test_bot_messages_excluded():
    digest = _run()
    # BotFeed's Nifty auto-post must not create a Nifty item
    assert all(i.canonical_symbol != "^NSEI" for i in digest.items)


def test_report_renders():
    from src import report

    digest = _run()
    md = report.render_markdown(digest)
    html = report.render_html(digest)
    assert "Stock Chat Digest" in md
    assert "<!doctype html>" in html
    assert "RELIANCE.NS" in md
