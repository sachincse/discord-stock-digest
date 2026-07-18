"""Core data models shared across the whole pipeline.

Everything downstream imports from here, so these dataclasses are the
contract between modules. Keep them dependency-free (stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Ingestion layer
# ---------------------------------------------------------------------------
@dataclass
class RawMessage:
    """A single Discord message, normalised into a source-agnostic shape.

    Produced by any ingestor (live bot, exported JSON, or test fixtures).
    """

    id: str
    author_id: str
    author_name: str
    timestamp: datetime  # timezone-aware, UTC
    content: str
    reply_to_id: Optional[str] = None
    thread_id: Optional[str] = None
    mentions: list[str] = field(default_factory=list)  # author ids or names
    is_bot: bool = False
    reactions: int = 0

    @property
    def clean_content(self) -> str:
        return (self.content or "").strip()


@dataclass
class Thread:
    """A disentangled conversation: a set of messages about one topic."""

    thread_id: str
    messages: list[RawMessage] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Rendered transcript, used as LLM input."""
        return "\n".join(
            f"[{m.author_name}] {m.clean_content}" for m in self.messages
        )


# ---------------------------------------------------------------------------
# Extraction layer
# ---------------------------------------------------------------------------
@dataclass
class StockMention:
    """One stock referenced inside one message, with extracted opinion."""

    canonical_symbol: str  # e.g. "RELIANCE.NS", "AAPL"
    company: str
    exchange: str  # "NSE" | "BSE" | "US"
    ticker_raw: str  # what actually appeared in the message

    author_id: str
    author_name: str
    timestamp: datetime
    thread_id: str
    message_id: str

    sentiment: str = "neutral"  # positive | negative | neutral
    recommendation: str = "unclear"  # buy|accumulate|hold|avoid|sell|unclear
    points: dict = field(default_factory=dict)  # case_study/future/problem
    evidence_quote: str = ""
    event_flags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    tickers_in_message: int = 1  # for list-spam (watchlist-dump) down-weighting


SENTIMENT_VALUE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


# ---------------------------------------------------------------------------
# Aggregation / reporting layer
# ---------------------------------------------------------------------------
@dataclass
class MarketSnapshot:
    """Objective market data for a symbol (from yfinance or a stub)."""

    symbol: str
    price: Optional[float] = None
    currency: str = ""
    change_1d_pct: Optional[float] = None
    change_5d_pct: Optional[float] = None
    change_1mo_pct: Optional[float] = None
    volume: Optional[float] = None
    avg_volume_30d: Optional[float] = None
    volume_ratio: Optional[float] = None  # today vs 30d avg
    pct_from_52w_high: Optional[float] = None
    pct_from_52w_low: Optional[float] = None
    news_count: int = 0
    # Derived flags (filled by market module):
    hype_flag: str = "unknown"  # hyped | normal | quiet | unknown
    performance_flag: str = "unknown"  # doing_well|mixed|doing_badly|unknown


@dataclass
class TrustedStance:
    author_name: str
    weight: float
    sentiment: str
    recommendation: str
    quote: str


@dataclass
class Evidence:
    quote: str
    author_name: str
    message_id: str
    weight: float = 1.0


@dataclass
class StockDigestItem:
    """One stock's aggregated summary for the daily report."""

    canonical_symbol: str
    company: str
    exchange: str

    mention_count: int = 0
    distinct_authors: int = 0
    weighted_score: float = 0.0
    net_sentiment: float = 0.0  # -1..1 (author-weighted)
    consensus_recommendation: str = "unclear"

    positives: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    event_flags: list[str] = field(default_factory=list)
    trusted_stances: list[TrustedStance] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    market: Optional[MarketSnapshot] = None

    relevance_score: float = 0.0
    breaking_news_score: float = 0.0
    surfaced_reason: str = ""

    # cross-day trend (filled from the SQLite store when enabled)
    is_new: bool = False              # not seen in the trailing baseline window
    baseline_mentions: float = 0.0    # trailing-average daily mentions
    mention_momentum: float = 0.0     # today's mentions ÷ baseline (0 = no data)

    @property
    def sentiment_label(self) -> str:
        if self.net_sentiment > 0.25:
            return "positive"
        if self.net_sentiment < -0.25:
            return "negative"
        return "mixed"


@dataclass
class DailyDigest:
    """The full report object rendered by the report module."""

    report_date: date
    channel_name: str
    generated_at: datetime
    total_messages: int = 0
    analyzed_messages: int = 0
    items: list[StockDigestItem] = field(default_factory=list)
    extractor: str = ""  # which extractor produced the mentions
