"""Manual copy-paste ingestion — the permission-free path for plain members."""
from pathlib import Path

from src import ingest, pipeline
from src.config import Config
from src.extract import HeuristicExtractor
from src.gazetteer import Gazetteer

ROOT = Path(__file__).resolve().parents[1]
PASTE = ROOT / "data" / "sample_paste.txt"


def test_parses_author_formats():
    msgs = ingest.load_messages_from_text(PASTE)
    by_content = {m.content: m for m in msgs}
    # [Name] bracket format
    assert any(m.author_name == "Rajesh" and "RIL" in m.content for m in msgs)
    # Name: colon format
    assert any(m.author_name == "Priya" and "Reliance" in m.content for m in msgs)
    assert any(m.author_name == "Vikram" and "NVDA" in m.content for m in msgs)


def test_timestamp_lines_skipped():
    msgs = ingest.load_messages_from_text(PASTE)
    assert not any("Today at" in m.content for m in msgs)


def test_all_caps_ticker_not_treated_as_author():
    # "$SUZLON to the moon..." must NOT become author "$SUZLON"; and a bare
    # "RVNL bags..." line stays content (no lowercase name before a colon).
    msgs = ingest.load_messages_from_text(PASTE)
    authors = {m.author_name for m in msgs}
    assert not any(a.upper() == a and len(a) <= 6 and a.isalpha() for a in authors if a != "member")


def test_pipeline_runs_on_pasted_text():
    msgs = ingest.load_messages_from_text(PASTE)
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    cfg = Config()
    cfg.trusted_users = {"Rajesh": 3.0, "Priya": 2.5, "Vikram": 2.0}
    cfg.trusted_threshold = 2.0
    cfg.use_db = False
    digest = pipeline.run(msgs, cfg, gazetteer=gz, extractor=HeuristicExtractor(),
                          now=max(m.timestamp for m in msgs))
    syms = {i.canonical_symbol for i in digest.items}
    assert "RELIANCE.NS" in syms
    assert "SUZLON.NS" in syms
    # RVNL order win should still surface even though it was an unattributed line
    assert "RVNL.NS" in syms
