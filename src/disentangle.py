"""Stage 2 — conversation disentanglement.

Interleaved multi-party chat -> coherent threads, using Discord's native
signals first (explicit replies, thread membership, @mentions) and a light
heuristic (shared ticker within a time window, same-author bursts) for the
residue. This is deliberately deterministic and free — the LLM is only
needed for genuinely ambiguous orphans, which we don't attempt here.
"""
from __future__ import annotations

from datetime import timedelta

from .gazetteer import Gazetteer
from .models import RawMessage, Thread


class _UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def build_threads(
    messages: list[RawMessage],
    gz: Gazetteer | None = None,
    window_minutes: int = 15,
) -> list[Thread]:
    if not messages:
        return []

    msgs = sorted(messages, key=lambda m: m.timestamp)
    by_id = {m.id: m for m in msgs}
    uf = _UnionFind([m.id for m in msgs])
    window = timedelta(minutes=window_minutes)

    # Index of each author's message ids in chronological order.
    last_by_author: dict[str, str] = {}
    tickers_cache: dict[str, set[str]] = {}

    def tickers(m: RawMessage) -> set[str]:
        if gz is None:
            return set()
        if m.id not in tickers_cache:
            tickers_cache[m.id] = set(gz.candidate_symbols(m.content))
        return tickers_cache[m.id]

    for i, m in enumerate(msgs):
        # (a) explicit reply edge — strongest signal
        if m.reply_to_id and m.reply_to_id in by_id:
            uf.union(m.reply_to_id, m.id)

        # (b) native thread membership
        if m.thread_id:
            # link to the previous message sharing this thread_id
            for prev in reversed(msgs[:i]):
                if prev.thread_id == m.thread_id:
                    uf.union(prev.id, m.id)
                    break

        # (c) @mention -> that user's most recent prior message (within window)
        for mention in m.mentions:
            key = mention.lower()
            for prev in reversed(msgs[:i]):
                if (
                    prev.author_name.lower() == key
                    and m.timestamp - prev.timestamp <= window
                ):
                    uf.union(prev.id, m.id)
                    break

        # (d) same author burst within window
        prev_id = last_by_author.get(m.author_id)
        if prev_id and m.timestamp - by_id[prev_id].timestamp <= window:
            uf.union(prev_id, m.id)
        last_by_author[m.author_id] = m.id

        # (e) shared ticker within window (topic continuity)
        my_tickers = tickers(m)
        if my_tickers:
            for prev in reversed(msgs[:i]):
                if m.timestamp - prev.timestamp > window:
                    break
                if my_tickers & tickers(prev):
                    uf.union(prev.id, m.id)
                    break

    # Group by connected component.
    groups: dict[str, list[RawMessage]] = {}
    for m in msgs:
        root = uf.find(m.id)
        groups.setdefault(root, []).append(m)

    threads = []
    for idx, (_, group) in enumerate(
        sorted(groups.items(), key=lambda kv: kv[1][0].timestamp)
    ):
        tid = f"t{idx:03d}"
        for m in group:
            m.thread_id = tid
        threads.append(Thread(thread_id=tid, messages=group))
    return threads
