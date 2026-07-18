"""Tests for the shared LLM extractor logic (Gemini/Ollama), without a server.

We monkeypatch ``_complete`` so the prompt/parse/validate/map pipeline is
exercised deterministically — no network, no Ollama, no Gemini key needed.
"""
from datetime import datetime, timezone
from pathlib import Path

from src.config import Config
from src.extract import OllamaExtractor, _extract_rows
from src.gazetteer import Gazetteer
from src.models import RawMessage, Thread

ROOT = Path(__file__).resolve().parents[1]


def test_extract_rows_accepts_both_shapes():
    assert _extract_rows({"stocks": [{"a": 1}]}) == [{"a": 1}]
    assert _extract_rows([{"a": 1}]) == [{"a": 1}]
    assert _extract_rows("garbage") == []
    assert _extract_rows({}) == []


def _thread():
    msgs = [
        RawMessage(id="1", author_id="u1", author_name="Rajesh",
                   timestamp=datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc),
                   content="RIL looks strong, buying more"),
    ]
    return Thread(thread_id="t0", messages=msgs)


def test_ollama_maps_stances_and_rejects_hallucinations(monkeypatch):
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    cfg = Config()
    ext = OllamaExtractor(cfg)

    rows = [
        {"canonical_symbol": "RELIANCE.NS", "company": "Reliance", "stances": [
            {"author": "user1", "sentiment": "positive", "recommendation": "buy",
             "evidence_quote": "RIL looks strong", "confidence": 0.9}]},
        {"canonical_symbol": "FAKE.NS", "company": "Fake", "stances": [
            {"author": "user1", "sentiment": "positive", "recommendation": "buy",
             "evidence_quote": "x", "confidence": 0.9}]},
    ]
    monkeypatch.setattr(ext, "_complete", lambda prompt: rows)

    mentions = ext.extract([_thread()], gz, cfg)
    syms = {m.canonical_symbol for m in mentions}
    assert "RELIANCE.NS" in syms
    assert "FAKE.NS" not in syms  # hallucinated ticker rejected by the gazetteer

    m = next(x for x in mentions if x.canonical_symbol == "RELIANCE.NS")
    assert m.sentiment == "positive"
    assert m.recommendation == "buy"
    assert m.message_id == "1"          # quote mapped back to the source message
    assert m.author_name == "Rajesh"


def test_low_confidence_stance_dropped(monkeypatch):
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    cfg = Config()
    cfg.min_confidence = 0.5
    ext = OllamaExtractor(cfg)
    rows = [{"canonical_symbol": "RELIANCE.NS", "stances": [
        {"author": "user1", "sentiment": "positive", "recommendation": "buy",
         "evidence_quote": "RIL looks strong", "confidence": 0.2}]}]
    monkeypatch.setattr(ext, "_complete", lambda prompt: rows)
    assert ext.extract([_thread()], gz, cfg) == []


def test_thread_without_candidates_skips_llm(monkeypatch):
    gz = Gazetteer.load(ROOT / "data" / "symbols.csv")
    ext = OllamaExtractor(Config())
    called = {"n": 0}

    def _boom(prompt):
        called["n"] += 1
        return []

    monkeypatch.setattr(ext, "_complete", _boom)
    noise = Thread(thread_id="t0", messages=[
        RawMessage(id="1", author_id="u1", author_name="A",
                   timestamp=datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc),
                   content="good morning everyone")])
    assert ext.extract([noise], gz, Config()) == []
    assert called["n"] == 0  # no LLM call spent on a thread with no tickers
