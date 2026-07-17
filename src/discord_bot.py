"""Live Discord ingestion — Path A (official bot, added by a server admin).

This is the ONLY Terms-of-Service-compliant way to read a channel you don't
own. A regular member cannot add a bot; someone with "Manage Server" must
install it once (see docs/owner_message.md). Requires the Message Content
Intent toggle enabled in the Developer Portal.

Usage is one-shot: log in, page back through the channel's history for the
lookback window, return normalised messages, log out.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from .config import Config
from .models import RawMessage


async def fetch_messages_async(config: Config) -> list[RawMessage]:
    import discord  # type: ignore

    if not config.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")
    if not config.channel_id:
        raise RuntimeError("DISCORD_CHANNEL_ID not set")

    intents = discord.Intents.default()
    intents.message_content = True  # privileged; enable in the Developer Portal
    client = discord.Client(intents=intents)
    collected: list[RawMessage] = []
    after = datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)

    @client.event
    async def on_ready():  # noqa: D401
        try:
            channel = client.get_channel(int(config.channel_id)) or await client.fetch_channel(
                int(config.channel_id)
            )
            async for msg in channel.history(limit=None, after=after, oldest_first=True):
                collected.append(_to_raw(msg))
        finally:
            await client.close()

    await client.start(config.discord_bot_token)
    return collected


def _to_raw(msg) -> RawMessage:
    ref = getattr(msg, "reference", None)
    reply_to = str(ref.message_id) if ref and ref.message_id else None
    thread_id = None
    thread = getattr(msg, "thread", None)
    if thread is not None:
        thread_id = str(thread.id)
    elif getattr(msg.channel, "type", None) and "thread" in str(msg.channel.type):
        thread_id = str(msg.channel.id)
    return RawMessage(
        id=str(msg.id),
        author_id=str(msg.author.id),
        author_name=msg.author.display_name or msg.author.name,
        timestamp=msg.created_at.astimezone(timezone.utc),
        content=msg.content or "",
        reply_to_id=reply_to,
        thread_id=thread_id,
        mentions=[m.display_name or m.name for m in getattr(msg, "mentions", [])],
        is_bot=bool(getattr(msg.author, "bot", False)),
        reactions=sum(r.count for r in getattr(msg, "reactions", [])),
    )


def fetch_messages(config: Config) -> list[RawMessage]:
    """Synchronous wrapper around the async fetch."""
    return asyncio.run(fetch_messages_async(config))
