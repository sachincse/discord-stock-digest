"""Stage 3 — extract per-stock opinions from disentangled threads.

Interchangeable extractors implement the same ``Extractor`` interface:

  * ``HeuristicExtractor`` — zero-dependency, offline, deterministic. Used by
    ``--selftest`` and as the automatic fallback when no LLM is configured.
  * ``GeminiExtractor`` — Google Gemini (free tier) for real language
    understanding: nuance, conditionals, sarcasm, implicit sentiment.
  * ``OllamaExtractor`` — a local Ollama model: same LLM quality tier, but
    fully private and free (nothing leaves the machine).

All return ``list[StockMention]``. Every symbol is validated against the
gazetteer, so no extractor can emit a ticker that doesn't exist
("valid JSON is not correct JSON").
"""
from __future__ import annotations

import json
import re
from typing import Protocol

from .config import Config
from .gazetteer import Gazetteer
from .models import RawMessage, StockMention, Thread
from .noise_filter import EVENT_KEYWORDS, _has_term, _norm

# --- keyword lexicons for the heuristic path -----------------------------
POS_WORDS = {
    "bullish", "buy", "accumulate", "breakout", "multibagger", "strong",
    "good", "great", "undervalued", "long", "rally", "upside", "target",
    "gem", "quality", "growth", "beat", "outperform", "upgrade", "moat",
    "add", "loading", "conviction", "solid", "compounder",
}
NEG_WORDS = {
    "bearish", "sell", "avoid", "dump", "crash", "weak", "loss", "down",
    "overvalued", "short", "correction", "risk", "risky", "trap", "fraud",
    "scam", "debt", "expensive", "exit", "book profit", "downgrade",
    "underperform", "miss", "concern", "worried", "falling", "red flag",
}
BUY_RE = re.compile(r"\b(buy|accumulat\w+|add(?:ing)?|load(?:ing)?)\b", re.I)
SELL_RE = re.compile(r"\b(sell|exit|book\s*profit|dump)\b", re.I)
AVOID_RE = re.compile(r"\b(avoid|stay\s*away|steer\s*clear)\b", re.I)
HOLD_RE = re.compile(r"\b(hold|holding|wait|watch)\b", re.I)

# Negators flip the polarity of a nearby sentiment word ("not bullish").
NEGATORS = {
    "not", "no", "never", "cant", "cannot", "dont", "don't", "isnt", "isn't",
    "arent", "aren't", "wont", "won't", "hardly", "barely", "nt", "aint",
}
# Finance/chat emoji carry first-class sentiment that words miss.
BULL_EMOJI = ["🚀", "🌙", "🌚", "📈", "💎", "🟢", "🔥", "🐂", "🤑", "💰", "⬆"]
BEAR_EMOJI = ["📉", "🔴", "🐻", "💀", "⚠", "⬇", "🩸", "🤡"]


class Extractor(Protocol):
    name: str

    def extract(
        self, threads: list[Thread], gz: Gazetteer, config: Config
    ) -> list[StockMention]: ...


# =========================================================================
# Heuristic (offline) extractor
# =========================================================================
class HeuristicExtractor:
    name = "heuristic"

    def extract(
        self, threads: list[Thread], gz: Gazetteer, config: Config
    ) -> list[StockMention]:
        mentions: list[StockMention] = []
        for thread in threads:
            for msg in thread.messages:
                cands = gz.resolve(msg.content)
                for cand in cands:
                    mentions.append(self._mention(msg, thread, cand, len(cands)))
        return mentions

    def _mention(self, msg: RawMessage, thread: Thread, cand, n_tickers: int = 1) -> StockMention:
        content = msg.clean_content
        low = _norm(content)
        sentiment = self._sentiment(content)
        rec = self._recommendation(low, sentiment)
        events = sorted({e for e in EVENT_KEYWORDS if _has_term(low, {e})})
        points = {}
        if "if " in low or "expect" in low or "target" in low:
            points["future_expectation"] = msg.clean_content
        if any(w in low for w in ("problem", "risk", "debt", "concern", "issue")):
            points["problem_or_risk"] = msg.clean_content
        confidence = 0.75 if cand.matched_text.startswith("$") else 0.55
        return StockMention(
            canonical_symbol=cand.canonical_symbol,
            company=cand.entry.company,
            exchange=cand.entry.exchange,
            ticker_raw=cand.matched_text,
            author_id=msg.author_id,
            author_name=msg.author_name,
            timestamp=msg.timestamp,
            thread_id=thread.thread_id,
            message_id=msg.id,
            sentiment=sentiment,
            recommendation=rec,
            points=points,
            evidence_quote=msg.clean_content,
            event_flags=events,
            confidence=confidence,
            tickers_in_message=max(1, n_tickers),
        )

    @staticmethod
    def _sentiment(text: str) -> str:
        """Negation-, caps- and emoji-aware bag-of-words polarity (offline)."""
        low = text.lower()
        tokens = re.findall(r"[a-z']+", low)
        pos = neg = 0
        for i, tok in enumerate(tokens):
            polarity = 1 if tok in POS_WORDS else (-1 if tok in NEG_WORDS else 0)
            if not polarity:
                continue
            if any(t in NEGATORS for t in tokens[max(0, i - 2):i]):
                polarity = -polarity  # "not bullish" -> negative
            pos += polarity > 0
            neg += polarity < 0
        pos += sum(text.count(e) for e in BULL_EMOJI)
        neg += sum(text.count(e) for e in BEAR_EMOJI)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"

    @staticmethod
    def _recommendation(low: str, sentiment: str) -> str:
        if AVOID_RE.search(low):
            return "avoid"
        if SELL_RE.search(low):
            return "sell"
        if BUY_RE.search(low):
            return "buy" if "accumulat" not in low else "accumulate"
        if HOLD_RE.search(low):
            return "hold"
        return "unclear"


# =========================================================================
# LLM extractors (Gemini free tier + local Ollama) — shared base
# =========================================================================
# Object-root schema (a "stocks" array). Works as Gemini's response_schema
# AND as Ollama's `format` for constrained decoding.
_STANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "author": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "recommendation": {
            "type": "string",
            "enum": ["buy", "accumulate", "hold", "avoid", "sell", "unclear"],
        },
        "case_study": {"type": "string"},
        "future_expectation": {"type": "string"},
        "problem_or_risk": {"type": "string"},
        "event_flags": {"type": "array", "items": {"type": "string"}},
        "evidence_quote": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["author", "sentiment", "recommendation", "evidence_quote"],
}
_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "stocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical_symbol": {"type": "string"},
                    "company": {"type": "string"},
                    "stances": {"type": "array", "items": _STANCE_SCHEMA},
                },
                "required": ["canonical_symbol", "stances"],
            },
        }
    },
    "required": ["stocks"],
}

_PROMPT = """You analyse a single Discord conversation from a stock-discussion \
community. Extract what participants said about specific stocks.

RULES:
- Use ONLY canonical symbols from this candidate list (do not invent tickers):
{candidates}
- Attribute each opinion to the author who said it (use the [name] tags).
- Copy a short verbatim quote into evidence_quote as proof.
- sentiment reflects the author's stance on the stock.
- recommendation is their explicit or clearly-implied call.
- event_flags: note concrete events (results, merger, order win, SEBI action, \
upper/lower circuit, etc.) if mentioned.
- Respect conditionals ("if it breaks 200 I'll buy" is not a current buy) and \
sarcasm. Use "neutral"/"unclear" when genuinely unsure.
- Ignore noise, greetings, and off-topic chatter.
- Return JSON of the form {{"stocks": [...]}}.

CONVERSATION:
{conversation}
"""


def _extract_rows(parsed) -> list[dict]:
    """Accept either a bare list or a {"stocks": [...]} object."""
    if isinstance(parsed, dict):
        return parsed.get("stocks") or parsed.get("results") or []
    if isinstance(parsed, list):
        return parsed
    return []


class _LLMExtractor:
    """Shared per-thread prompt/parse/validate loop for LLM backends."""

    name = "llm"

    def __init__(self, config: Config):
        self.config = config

    def extract(
        self, threads: list[Thread], gz: Gazetteer, config: Config
    ) -> list[StockMention]:
        mentions: list[StockMention] = []
        for thread in threads:
            candidates = sorted(
                {c.canonical_symbol for m in thread.messages for c in gz.resolve(m.content)}
            )
            if not candidates:
                continue  # nothing to extract; don't spend a call
            prompt = _PROMPT.format(
                candidates="\n".join(f"- {c}" for c in candidates),
                conversation=_anonymise(thread, self.config.anonymize_usernames),
            )
            try:
                rows = self._complete(prompt)
            except Exception as exc:  # degrade gracefully, keep the digest alive
                print(f"[{self.name}] thread {thread.thread_id} failed: {exc}")
                continue
            mentions.extend(self._to_mentions(rows, thread, gz))
        return mentions

    def _complete(self, prompt: str) -> list[dict]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _to_mentions(self, rows: list[dict], thread: Thread, gz: Gazetteer) -> list[StockMention]:
        out: list[StockMention] = []
        by_name = {m.author_name.lower(): m for m in thread.messages}
        for row in rows:
            symbol = (row or {}).get("canonical_symbol", "")
            entry = gz.get(symbol)
            if entry is None:  # reject hallucinated / invalid tickers
                continue
            for st in row.get("stances", []) or []:
                author = st.get("author", "?")
                msg = _match_message(thread, author, st.get("evidence_quote", ""), by_name)
                points = {
                    k: st[k]
                    for k in ("case_study", "future_expectation", "problem_or_risk")
                    if st.get(k)
                }
                conf = float(st.get("confidence", 0.6) or 0.6)
                if conf < self.config.min_confidence:
                    continue
                out.append(
                    StockMention(
                        canonical_symbol=symbol,
                        company=entry.company,
                        exchange=entry.exchange,
                        ticker_raw=symbol,
                        author_id=msg.author_id if msg else author,
                        author_name=msg.author_name if msg else author,
                        timestamp=msg.timestamp if msg else thread.messages[0].timestamp,
                        thread_id=thread.thread_id,
                        message_id=msg.id if msg else thread.messages[0].id,
                        sentiment=st.get("sentiment", "neutral"),
                        recommendation=st.get("recommendation", "unclear"),
                        points=points,
                        evidence_quote=st.get("evidence_quote", ""),
                        event_flags=list(st.get("event_flags", []) or []),
                        confidence=conf,
                    )
                )
        return out


class GeminiExtractor(_LLMExtractor):
    name = "gemini"

    def __init__(self, config: Config):
        super().__init__(config)
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            from google import genai  # type: ignore

            if not self.config.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not set")
            self._client = genai.Client(api_key=self.config.gemini_api_key)
        return self._client

    def _complete(self, prompt: str) -> list[dict]:
        client = self._client_lazy()
        resp = client.models.generate_content(
            model=self.config.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": _LLM_SCHEMA,
                "temperature": 0.1,
            },
        )
        return _extract_rows(json.loads(getattr(resp, "text", None) or "{}"))


class OllamaExtractor(_LLMExtractor):
    """Local, free, fully-private extraction via an Ollama server.

    No cloud, no quota, nothing leaves the machine — the privacy-preserving
    option. Requires a running Ollama (https://ollama.com) with the configured
    model pulled (e.g. ``ollama pull qwen2.5:3b``).
    """

    name = "ollama"

    def _complete(self, prompt: str) -> list[dict]:
        import requests

        url = f"{self.config.ollama_host.rstrip('/')}/api/chat"
        payload = {
            "model": self.config.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": _LLM_SCHEMA,  # constrained decoding -> valid JSON
            "options": {"temperature": 0.1},
        }
        resp = requests.post(url, json=payload, timeout=self.config.ollama_timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "{}")
        return _extract_rows(json.loads(content))


def _anonymise(thread: Thread, on: bool) -> str:
    if not on:
        return thread.text
    # Map real names -> stable pseudonyms so private names never hit the API,
    # but the LLM can still attribute stances per distinct speaker.
    names: dict[str, str] = {}
    lines = []
    for m in thread.messages:
        if m.author_name not in names:
            names[m.author_name] = f"user{len(names) + 1}"
        lines.append(f"[{names[m.author_name]}] {m.clean_content}")
    return "\n".join(lines)


def _match_message(thread: Thread, author: str, quote: str, by_name: dict):
    """Best-effort map an LLM stance back to a concrete source message."""
    q = (quote or "").strip().lower()[:40]
    if q:
        for m in thread.messages:
            if q and q in m.clean_content.lower():
                return m
    # anonymised authors look like "user3"
    if author.lower().startswith("user"):
        try:
            idx = int(author[4:]) - 1
            distinct = list(dict.fromkeys(m.author_name for m in thread.messages))
            if 0 <= idx < len(distinct):
                target = distinct[idx].lower()
                return by_name.get(target)
        except ValueError:
            pass
    return by_name.get(author.lower())


def select_extractor(config: Config) -> Extractor:
    """Choose an extractor from ``config.extractor_backend``.

    - ``heuristic`` — offline rules (default fallback)
    - ``gemini``    — Google Gemini free tier (needs GEMINI_API_KEY)
    - ``ollama``    — local Ollama server (fully private, free)
    - ``auto``      — Gemini if a key is present, else heuristic
    """
    backend = (config.extractor_backend or "auto").lower()
    if backend == "heuristic":
        return HeuristicExtractor()
    if backend == "ollama":
        return OllamaExtractor(config)
    if backend == "gemini":
        try:
            import google.genai  # noqa: F401
            return GeminiExtractor(config)
        except Exception:
            print("[extract] google-genai not installed; using heuristic extractor")
            return HeuristicExtractor()
    # auto
    if config.gemini_api_key:
        try:
            import google.genai  # noqa: F401
            return GeminiExtractor(config)
        except Exception:
            print("[extract] google-genai not installed; using heuristic extractor")
    return HeuristicExtractor()
