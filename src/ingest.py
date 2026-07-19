"""Message ingestion — turn any source into ``list[RawMessage]``.

Supported sources:
  * live Discord bot  -> see ``discord_bot.py``
  * exported JSON     -> DiscordChatExporter format OR this project's simple
                         fixture format (used by tests / ``--selftest``)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import RawMessage


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    s = str(value).strip()
    # DiscordChatExporter emits ISO-8601 with offset, sometimes trailing 'Z'.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # last-ditch: drop sub-second / timezone name
        dt = datetime.fromisoformat(s.split(".")[0])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_messages_from_json(path: str | Path) -> list[RawMessage]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # DiscordChatExporter: {"messages": [...], "channel": {...}}
    if isinstance(data, dict) and "messages" in data:
        return _from_exporter(data["messages"])
    if isinstance(data, list):
        return _from_simple(data)
    raise ValueError(f"Unrecognised message JSON structure in {path}")


def _from_simple(rows: list[dict]) -> list[RawMessage]:
    out: list[RawMessage] = []
    for r in rows:
        out.append(
            RawMessage(
                id=str(r["id"]),
                author_id=str(r.get("author_id", r.get("author", "?"))),
                author_name=str(r.get("author", r.get("author_name", "?"))),
                timestamp=_parse_ts(r["timestamp"]),
                content=r.get("content", ""),
                reply_to_id=(str(r["reply_to"]) if r.get("reply_to") else None),
                thread_id=(str(r["thread_id"]) if r.get("thread_id") else None),
                mentions=[str(m) for m in r.get("mentions", [])],
                is_bot=bool(r.get("is_bot", False)),
                reactions=int(r.get("reactions", 0)),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Manual paste ingestion  (the permission-free, ToS-clean path)
# ---------------------------------------------------------------------------
# For a member who can't have a bot added: read the channel yourself and copy
# the day's messages into a text file. This just PARSES that text — no
# automation, no token, no scraping. Two optional per-line author formats give
# proper trust-weighting; plain text still yields stock mentions + sentiment.
_TS_ONLY = re.compile(
    r"^\[?\s*(today|yesterday)\b.*$|^\[?\s*\d{1,2}[:/]\d{1,2}([:/ ].*)?$"
    r"|^\d{1,2}/\d{1,2}/\d{2,4}.*$",
    re.I,
)
_BRACKET = re.compile(r"^\[([^\]]{1,32})\]\s*(.*\S)?\s*$")
_COLON = re.compile(r"^([A-Za-z][\w.\- ]{0,23}):\s+(.+)$")


def _looks_like_name(s: str) -> bool:
    # Real usernames carry a lowercase letter; all-caps "RIL:" is a ticker line,
    # not an author, so it stays as content.
    return any(c.islower() for c in s) and len(s.split()) <= 4


def load_messages_from_text(path: str | Path, now: datetime | None = None) -> list[RawMessage]:
    now = now or datetime.now(timezone.utc)
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    parsed: list[tuple[str, str]] = []  # (author, content)
    current_author: str | None = None
    for line in lines:
        s = line.strip()
        if not s or _TS_ONLY.match(s):
            continue
        m = _BRACKET.match(s)
        if m:
            current_author = m.group(1).strip()
            content = (m.group(2) or "").strip()
            if not content:  # "[Rajesh]" header on its own line
                continue
            parsed.append((current_author, content))
            continue
        m = _COLON.match(s)
        if m and _looks_like_name(m.group(1).strip()):
            current_author = m.group(1).strip()
            parsed.append((current_author, m.group(2).strip()))
            continue
        parsed.append((current_author or "member", s))

    n = len(parsed)
    out: list[RawMessage] = []
    for i, (author, content) in enumerate(parsed):
        out.append(
            RawMessage(
                id=str(i + 1),
                author_id=author.lower(),
                author_name=author,
                # spread over the recent past so ordering + recency behave
                timestamp=now - timedelta(seconds=(n - i) * 30),
                content=content,
            )
        )
    return out


def _from_exporter(rows: list[dict]) -> list[RawMessage]:
    out: list[RawMessage] = []
    for r in rows:
        author = r.get("author", {}) or {}
        ref = r.get("reference") or {}
        reactions = sum(int(x.get("count", 0)) for x in (r.get("reactions") or []))
        out.append(
            RawMessage(
                id=str(r["id"]),
                author_id=str(author.get("id", "?")),
                author_name=str(author.get("nickname") or author.get("name", "?")),
                timestamp=_parse_ts(r["timestamp"]),
                content=r.get("content", ""),
                reply_to_id=(str(ref["messageId"]) if ref.get("messageId") else None),
                thread_id=None,
                mentions=[str(m.get("name", "")) for m in (r.get("mentions") or [])],
                is_bot=bool(author.get("isBot", False)),
                reactions=reactions,
            )
        )
    return out
