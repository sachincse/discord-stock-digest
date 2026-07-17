"""Stage 4 — objective market data to ground the "hype / doing well or badly"
signal in numbers, not just chat vibes.

``YFinanceProvider`` uses a single batched download (the documented way to
avoid Yahoo's 429 throttling) and degrades gracefully to ``None`` fields on
any failure. ``StubMarketProvider`` returns deterministic pseudo-data so the
pipeline and sample report run fully offline.
"""
from __future__ import annotations

import zlib
from typing import Iterable, Protocol

from .models import MarketSnapshot


class MarketProvider(Protocol):
    name: str

    def fetch(self, symbols: Iterable[str]) -> dict[str, MarketSnapshot]: ...


def apply_flags(s: MarketSnapshot) -> MarketSnapshot:
    """Derive hype_flag / performance_flag from the raw numbers."""
    # Performance
    d1, d5 = s.change_1d_pct, s.change_5d_pct
    if d5 is not None:
        if d5 >= 3 and (d1 or 0) >= 0:
            s.performance_flag = "doing_well"
        elif d5 <= -3 and (d1 or 0) <= 0:
            s.performance_flag = "doing_badly"
        else:
            s.performance_flag = "mixed"
    elif d1 is not None:
        s.performance_flag = "doing_well" if d1 >= 2 else "doing_badly" if d1 <= -2 else "mixed"

    # Hype
    vr, news = s.volume_ratio, s.news_count
    if (vr is not None and vr >= 2.0) or news >= 5:
        s.hype_flag = "hyped"
    elif vr is not None and vr < 0.6:
        s.hype_flag = "quiet"
    elif vr is not None or news:
        s.hype_flag = "normal"
    return s


class StubMarketProvider:
    """Deterministic fake data for offline runs (clearly labelled as stub)."""

    name = "stub"

    def fetch(self, symbols: Iterable[str]) -> dict[str, MarketSnapshot]:
        out: dict[str, MarketSnapshot] = {}
        for sym in symbols:
            h = zlib.crc32(sym.encode())
            d1 = ((h % 1200) / 100.0) - 6.0            # -6%..+6%
            d5 = (((h >> 4) % 2400) / 100.0) - 12.0     # -12%..+12%
            d1mo = (((h >> 8) % 4000) / 100.0) - 20.0
            vr = 0.5 + ((h >> 12) % 190) / 100.0        # 0.5x..2.4x (spikes rarer)
            news = (h >> 16) % 7                         # 0..6
            snap = MarketSnapshot(
                symbol=sym,
                price=round(100 + (h % 90000) / 100.0, 2),
                currency="INR" if sym.endswith((".NS", ".BO")) or sym.startswith("^NSE") else "USD",
                change_1d_pct=round(d1, 2),
                change_5d_pct=round(d5, 2),
                change_1mo_pct=round(d1mo, 2),
                volume=float((h % 5000000) + 100000),
                avg_volume_30d=float((h % 3000000) + 200000),
                volume_ratio=round(vr, 2),
                pct_from_52w_high=round(-((h >> 20) % 4000) / 100.0, 2),
                pct_from_52w_low=round(((h >> 22) % 8000) / 100.0, 2),
                news_count=news,
            )
            out[sym] = apply_flags(snap)
        return out


class YFinanceProvider:
    name = "yfinance"

    def fetch(self, symbols: Iterable[str]) -> dict[str, MarketSnapshot]:
        symbols = [s for s in symbols if s]
        out: dict[str, MarketSnapshot] = {}
        if not symbols:
            return out
        try:
            import yfinance as yf  # type: ignore
        except Exception:
            print("[market] yfinance not installed; skipping market data")
            return out

        try:
            data = yf.download(
                tickers=" ".join(symbols),
                period="3mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as exc:
            print(f"[market] batch download failed: {exc}")
            return out

        for sym in symbols:
            try:
                out[sym] = apply_flags(self._snapshot(sym, data, yf))
            except Exception as exc:
                print(f"[market] {sym}: {exc}")
                out[sym] = MarketSnapshot(symbol=sym)
        return out

    @staticmethod
    def _snapshot(sym, data, yf) -> MarketSnapshot:
        import math

        try:
            df = data[sym] if sym in getattr(data, "columns", []) or True else data
        except Exception:
            df = data
        # When only one ticker is requested yfinance returns a flat frame.
        try:
            close = df["Close"].dropna() if "Close" in df else data["Close"][sym].dropna()
            vol = df["Volume"].dropna() if "Volume" in df else data["Volume"][sym].dropna()
        except Exception:
            close = data["Close"].dropna()
            vol = data["Volume"].dropna()

        snap = MarketSnapshot(symbol=sym)
        if len(close) == 0:
            return snap
        last = float(close.iloc[-1])
        snap.price = round(last, 2)

        def pct(n):
            if len(close) > n:
                prev = float(close.iloc[-1 - n])
                if prev:
                    return round((last - prev) / prev * 100, 2)
            return None

        snap.change_1d_pct = pct(1)
        snap.change_5d_pct = pct(5)
        snap.change_1mo_pct = pct(21)

        if len(vol):
            snap.volume = float(vol.iloc[-1])
            avg = float(vol.tail(30).mean())
            snap.avg_volume_30d = round(avg, 2)
            if avg:
                snap.volume_ratio = round(snap.volume / avg, 2)

        hi, lo = float(close.max()), float(close.min())
        if hi:
            snap.pct_from_52w_high = round((last - hi) / hi * 100, 2)
        if lo:
            snap.pct_from_52w_low = round((last - lo) / lo * 100, 2)

        # Best-effort news count for the "big news" signal.
        try:
            snap.news_count = len(yf.Ticker(sym).news or [])
        except Exception:
            snap.news_count = 0
        if math.isnan(snap.price or float("nan")):
            snap.price = None
        return snap


def select_provider(use_market: bool, live: bool) -> MarketProvider | None:
    if not use_market:
        return None
    return YFinanceProvider() if live else StubMarketProvider()
