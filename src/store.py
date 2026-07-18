"""SQLite persistence — raw messages, extracted mentions, and daily rollups.

Enables:
  * **idempotent ingestion** — messages upsert by id, so re-runs never
    double-count and a crashed run can resume;
  * **cross-day trends** — a trailing baseline of daily mention counts powers
    "🆕 new today" and mention-momentum (today vs the last N days), which is a
    stronger "hyped" signal than a single day's volume;
  * **history** — every day's ranked digest is kept for later analysis.

Pure stdlib (``sqlite3``); safe to disable entirely (``use_db: false``).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .models import DailyDigest, RawMessage, StockDigestItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    author_id    TEXT,
    author_name  TEXT,
    timestamp    TEXT,
    content      TEXT,
    reply_to_id  TEXT,
    thread_id    TEXT,
    is_bot       INTEGER,
    reactions    INTEGER,
    fetched_at   TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    report_date       TEXT PRIMARY KEY,
    channel_name      TEXT,
    total_messages    INTEGER,
    analyzed_messages INTEGER,
    extractor         TEXT,
    generated_at      TEXT
);
CREATE TABLE IF NOT EXISTS daily_counts (
    report_date        TEXT,
    canonical_symbol   TEXT,
    company            TEXT,
    exchange           TEXT,
    mention_count      INTEGER,
    distinct_authors   INTEGER,
    net_sentiment      REAL,
    weighted_score     REAL,
    relevance_score    REAL,
    breaking_news_score REAL,
    consensus          TEXT,
    PRIMARY KEY (report_date, canonical_symbol)
);
CREATE TABLE IF NOT EXISTS mentions (
    run_date         TEXT,
    canonical_symbol TEXT,
    author_id        TEXT,
    author_name      TEXT,
    timestamp        TEXT,
    thread_id        TEXT,
    message_id       TEXT,
    sentiment        TEXT,
    recommendation   TEXT,
    evidence_quote   TEXT,
    event_flags      TEXT,
    confidence       REAL
);
CREATE INDEX IF NOT EXISTS ix_daily_symbol ON daily_counts (canonical_symbol, report_date);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- ingestion ----------------------------------------------------
    def save_messages(self, messages: Iterable[RawMessage]) -> int:
        now = datetime.utcnow().isoformat()
        rows = [
            (
                m.id, m.author_id, m.author_name, m.timestamp.isoformat(),
                m.content, m.reply_to_id, m.thread_id, int(m.is_bot),
                m.reactions, now,
            )
            for m in messages
        ]
        cur = self.conn.executemany(
            """INSERT INTO messages
               (id, author_id, author_name, timestamp, content, reply_to_id,
                thread_id, is_bot, reactions, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO NOTHING""",
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def already_ran(self, report_date: date) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM runs WHERE report_date=?", (report_date.isoformat(),)
        )
        return cur.fetchone() is not None

    # -- trends (read BEFORE saving today) ----------------------------
    def baseline(
        self, symbol: str, report_date: date, days: int
    ) -> tuple[float, bool]:
        """Return ``(avg_daily_mentions_over_prior_window, is_new)``.

        Looks at the ``days`` days *before* ``report_date`` (today excluded).
        ``is_new`` = the symbol never appeared in that window.
        """
        start = (report_date - timedelta(days=days)).isoformat()
        end = report_date.isoformat()
        cur = self.conn.execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(mention_count),0) AS total
               FROM daily_counts
               WHERE canonical_symbol=? AND report_date>=? AND report_date<?""",
            (symbol, start, end),
        )
        row = cur.fetchone()
        n_days, total = row["n"], row["total"]
        if not n_days:
            return 0.0, True
        return total / days, False

    # -- persist a completed digest -----------------------------------
    def save_digest(self, digest: DailyDigest) -> None:
        rd = digest.report_date.isoformat()
        self.conn.execute(
            """INSERT INTO runs
               (report_date, channel_name, total_messages, analyzed_messages,
                extractor, generated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(report_date) DO UPDATE SET
                 total_messages=excluded.total_messages,
                 analyzed_messages=excluded.analyzed_messages,
                 extractor=excluded.extractor,
                 generated_at=excluded.generated_at""",
            (rd, digest.channel_name, digest.total_messages,
             digest.analyzed_messages, digest.extractor,
             digest.generated_at.isoformat()),
        )
        for it in digest.items:
            self.conn.execute(
                """INSERT INTO daily_counts
                   (report_date, canonical_symbol, company, exchange,
                    mention_count, distinct_authors, net_sentiment,
                    weighted_score, relevance_score, breaking_news_score, consensus)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(report_date, canonical_symbol) DO UPDATE SET
                     mention_count=excluded.mention_count,
                     distinct_authors=excluded.distinct_authors,
                     net_sentiment=excluded.net_sentiment,
                     weighted_score=excluded.weighted_score,
                     relevance_score=excluded.relevance_score,
                     breaking_news_score=excluded.breaking_news_score,
                     consensus=excluded.consensus""",
                (rd, it.canonical_symbol, it.company, it.exchange,
                 it.mention_count, it.distinct_authors, it.net_sentiment,
                 it.weighted_score, it.relevance_score, it.breaking_news_score,
                 it.consensus_recommendation),
            )
        self.conn.commit()

    def save_mentions(self, report_date: date, mentions) -> None:
        rd = report_date.isoformat()
        rows = [
            (
                rd, m.canonical_symbol, m.author_id, m.author_name,
                m.timestamp.isoformat(), m.thread_id, m.message_id,
                m.sentiment, m.recommendation, m.evidence_quote,
                json.dumps(m.event_flags), m.confidence,
            )
            for m in mentions
        ]
        self.conn.executemany(
            """INSERT INTO mentions
               (run_date, canonical_symbol, author_id, author_name, timestamp,
                thread_id, message_id, sentiment, recommendation, evidence_quote,
                event_flags, confidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()

    def history(self, symbol: str, limit: int = 30) -> list[dict]:
        cur = self.conn.execute(
            """SELECT report_date, mention_count, net_sentiment, relevance_score
               FROM daily_counts WHERE canonical_symbol=?
               ORDER BY report_date DESC LIMIT ?""",
            (symbol, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()


def enrich_trends(
    items: list[StockDigestItem],
    store: Optional[Store],
    report_date: date,
    days: int,
) -> None:
    """Attach baseline / momentum / is_new to each item (in place).

    Must run BEFORE ``store.save_digest`` so today's row isn't its own baseline.
    """
    if store is None:
        return
    for it in items:
        baseline, is_new = store.baseline(it.canonical_symbol, report_date, days)
        it.baseline_mentions = round(baseline, 2)
        it.is_new = is_new
        if baseline > 0:
            it.mention_momentum = round(it.mention_count / baseline, 2)
        elif not is_new:
            it.mention_momentum = 1.0
