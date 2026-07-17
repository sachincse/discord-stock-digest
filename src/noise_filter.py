"""Stage 1 — cheap deterministic noise removal.

Cuts the bulk of junk (bots, greetings, emoji-only, link-only) BEFORE any
expensive LLM work — but never drops a message that mentions a stock or a
market event, so terse-but-critical calls ("RELIANCE results beat!") survive.
"""
from __future__ import annotations

import re

from .gazetteer import Gazetteer
from .models import RawMessage

_URL = re.compile(r"https?://\S+")
_EMOJI_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)
_CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")

GREETINGS = {
    "gm", "gn", "good morning", "good night", "good evening", "hi", "hello",
    "hey", "thanks", "thank you", "ty", "lol", "lmao", "rofl", "ok", "okay",
    "yes", "no", "yep", "nope", "haha", "hahaha", "welcome", "wow", "nice",
    "great", "cool", "same", "sure", "hmm", "oh", "ah", "bye", "cya", "brb",
    "morning", "evening", "night", "congrats", "gg", "true", "agreed", "+1",
}

EVENT_KEYWORDS = {
    "results", "result", "earnings", "q1", "q2", "q3", "q4", "guidance",
    "merger", "acquisition", "acquire", "buyback", "dividend", "bonus",
    "split", "ipo", "listing", "delisting", "fraud", "scam", "sebi", "rbi",
    "order", "contract", "deal", "upper circuit", "lower circuit", "halt",
    "halted", "block deal", "bulk deal", "downgrade", "upgrade", "target",
    "breakout", "breakdown", "52 week high", "52-week high", "all time high",
    "ath", "profit", "loss", "revenue", "margin", "fii", "dii", "stake",
}

FINANCE_TERMS = {
    "stock", "share", "shares", "buy", "sell", "hold", "accumulate", "sl",
    "stoploss", "stop loss", "entry", "exit", "cmp", "pe", "p/e", "eps",
    "valuation", "overvalued", "undervalued", "bullish", "bearish", "long",
    "short", "portfolio", "invest", "investment", "multibagger", "swing",
    "intraday", "chart", "support", "resistance", "trend", "rally", "dip",
    "correction", "fundamentals", "technical", "book profit", "average",
}


def _norm(text: str) -> str:
    return _CUSTOM_EMOJI.sub("", text or "").strip().lower()


def _has_term(text_low: str, terms: set[str]) -> bool:
    for t in terms:
        if " " in t:
            if t in text_low:
                return True
        elif re.search(rf"\b{re.escape(t)}\b", text_low):
            return True
    return False


def is_relevant(msg: RawMessage, gz: Gazetteer) -> bool:
    """True if the message is worth keeping for analysis."""
    if msg.is_bot:
        return False
    content = msg.clean_content
    if not content:
        return False

    stripped = _CUSTOM_EMOJI.sub("", content).strip()
    if not stripped:
        return False

    # Always keep anything referencing a stock or a market event.
    if gz.candidate_symbols(content):
        return True
    low = _norm(content)
    if _has_term(low, EVENT_KEYWORDS) or _has_term(low, FINANCE_TERMS):
        return True

    # Otherwise drop obvious noise.
    if _EMOJI_ONLY.match(stripped):
        return False
    if _URL.sub("", stripped).strip() == "":  # link-only
        return False
    if low in GREETINGS:
        return False
    if len(stripped) < 3:
        return False
    # Short greeting-ish messages with no finance signal are noise.
    words = low.split()
    if len(words) <= 3 and all(w in GREETINGS for w in words):
        return False
    return True


def filter_messages(
    messages: list[RawMessage], gz: Gazetteer
) -> tuple[list[RawMessage], int]:
    """Return ``(kept, dropped_count)``."""
    kept = [m for m in messages if is_relevant(m, gz)]
    return kept, len(messages) - len(kept)
