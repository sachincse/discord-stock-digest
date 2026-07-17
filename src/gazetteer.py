"""Ticker gazetteer: turn casual chat text into validated stock symbols.

This is the guardrail that stops the LLM (and the heuristic extractor) from
inventing tickers. Everything downstream trusts ONLY symbols that resolve
here. Handles ``$CASHTAGS``, colloquial names ("RIL", "Bank Nifty"), and
skips ambiguous English words unless they are explicitly cashtagged.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# Tokens that look like tickers but are ordinary English/chat/finance words.
# They only count when written as a cashtag ("$ALL"), never as a bare word —
# even in all-caps, because chat is often shouted in caps. This is the
# collision blacklist every mature social-stock tool maintains; see
# docs/ROADMAP.md for auto-generating it from a wordlist ∩ symbol universe.
AMBIGUOUS = {
    "all", "on", "it", "arm", "key", "car", "good", "now", "see", "real",
    "so", "go", "cap", "buy", "sell", "hold", "add", "gem", "moat", "dd",
    "ath", "usa", "ceo", "imo", "yolo", "new", "one", "are", "the", "and",
    "for", "pat", "eps", "roe", "fii", "dii", "ipo", "atm", "otm", "itm",
    "pe", "bse", "vi", "us", "eu", "ai", "ev", "ir", "hr", "eod", "sl",
}

_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z.\-]{0,14})")


@dataclass(frozen=True)
class SymbolEntry:
    canonical_symbol: str
    company: str
    exchange: str


@dataclass(frozen=True)
class Candidate:
    entry: SymbolEntry
    matched_text: str

    @property
    def canonical_symbol(self) -> str:
        return self.entry.canonical_symbol


class Gazetteer:
    def __init__(self, entries: list[SymbolEntry], alias_map: dict[str, SymbolEntry]):
        self._entries = {e.canonical_symbol: e for e in entries}
        self._alias_map = alias_map  # alias.lower() -> entry
        # Pre-sort multi-word aliases longest-first for greedy matching.
        self._aliases_sorted = sorted(
            alias_map.keys(), key=lambda a: (-len(a), a)
        )

    # -- construction --------------------------------------------------
    @classmethod
    def load(cls, path: str | Path = "data/symbols.csv") -> "Gazetteer":
        entries: list[SymbolEntry] = []
        alias_map: dict[str, SymbolEntry] = {}
        with open(path, "r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                entry = SymbolEntry(
                    canonical_symbol=row["canonical_symbol"].strip(),
                    company=row["company"].strip(),
                    exchange=row["exchange"].strip(),
                )
                entries.append(entry)
                aliases = {entry.canonical_symbol, entry.company}
                # base ticker without exchange suffix
                base = entry.canonical_symbol.split(".")[0].lstrip("^")
                aliases.add(base)
                for a in (row.get("aliases") or "").split("|"):
                    a = a.strip()
                    if a:
                        aliases.add(a)
                for a in aliases:
                    key = a.lower()
                    if key and key not in alias_map:
                        alias_map[key] = entry
        return cls(entries, alias_map)

    # -- lookup --------------------------------------------------------
    def is_valid(self, symbol: str) -> bool:
        return symbol in self._entries

    def get(self, symbol: str) -> SymbolEntry | None:
        return self._entries.get(symbol)

    def all_symbols(self) -> list[str]:
        return list(self._entries.keys())

    def resolve(self, text: str) -> list[Candidate]:
        """Return de-duplicated candidate symbols found in ``text``."""
        if not text:
            return []
        found: dict[str, Candidate] = {}

        # 1) Cashtags: $RELIANCE, $AAPL — trusted even if ambiguous.
        for m in _CASHTAG.finditer(text):
            token = m.group(1)
            entry = self._alias_map.get(token.lower())
            if entry is None:
                base = token.split(".")[0]
                entry = self._alias_map.get(base.lower())
            if entry:
                found.setdefault(entry.canonical_symbol, Candidate(entry, "$" + token))

        # 2) Alias phrases (longest-first). Word-boundary matched.
        low = text.lower()
        for alias in self._aliases_sorted:
            if alias in AMBIGUOUS:
                continue  # only via cashtag (handled above)
            if len(alias) <= 2:
                continue  # too short to match safely as a bare word
            entry = self._alias_map[alias]
            short_token = " " not in alias and len(alias) <= 4
            if short_token:
                # Short bare tokens are acronym-style tickers (RIL, SBI, RVNL,
                # NVDA). Require ALL-CAPS in the original text so lowercase
                # prose ("it", "arm", "reliance's arm") never matches — the
                # single biggest precision win per social-stock research.
                if _word_present(text, alias.upper()):
                    found.setdefault(
                        entry.canonical_symbol, Candidate(entry, alias.upper())
                    )
            elif _word_present(low, alias):
                found.setdefault(entry.canonical_symbol, Candidate(entry, alias))

        return list(found.values())

    def candidate_symbols(self, text: str) -> list[str]:
        return [c.canonical_symbol for c in self.resolve(text)]


def _word_present(haystack_lower: str, needle_lower: str) -> bool:
    """Whole-word (boundary-aware) containment check."""
    start = 0
    n = len(needle_lower)
    while True:
        idx = haystack_lower.find(needle_lower, start)
        if idx == -1:
            return False
        before_ok = idx == 0 or not haystack_lower[idx - 1].isalnum()
        after = idx + n
        after_ok = after >= len(haystack_lower) or not haystack_lower[after].isalnum()
        if before_ok and after_ok:
            return True
        start = idx + 1
