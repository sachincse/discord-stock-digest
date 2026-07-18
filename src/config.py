"""Configuration loader.

Secrets come from environment variables (never committed). Non-secret
tuning lives in an optional ``config.yaml`` (copy ``config.example.yaml``).
Everything has a sane default so the pipeline runs out of the box in
``--selftest`` mode with zero configuration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml is optional for selftest
    yaml = None


def _env(*names: str) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _envbool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ReportConfig:
    output_dir: str = "out"
    to_file: bool = True
    to_email: bool = False
    to_telegram: bool = False
    to_discord: bool = False
    # secrets pulled from env at send time
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    email_to: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook_url: Optional[str] = None


@dataclass
class Config:
    # --- ingestion ---
    discord_bot_token: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: str = "stocks"
    lookback_hours: int = 24

    # --- AI extraction ---
    extractor_backend: str = "auto"  # auto | heuristic | gemini | ollama
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: int = 180
    anonymize_usernames: bool = True  # privacy: don't send real names to free LLM
    min_confidence: float = 0.35

    # --- persistence & cross-day trends ---
    db_path: str = "data/digest.db"
    use_db: bool = True
    momentum_baseline_days: int = 7  # trailing window for "hot vs baseline"
    momentum_threshold: float = 2.0  # today's mentions >= N× baseline => momentum

    # --- trust & ranking ---
    trusted_users: dict[str, float] = field(default_factory=dict)
    default_user_weight: float = 1.0
    trusted_threshold: float = 2.0
    top_n: int = 10
    breaking_news_threshold: float = 0.6
    recency_half_life_hours: float = 12.0

    # --- market data ---
    use_market_data: bool = True

    report: ReportConfig = field(default_factory=ReportConfig)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike | None = "config.yaml") -> "Config":
        data: dict[str, Any] = {}
        if path and Path(path).exists() and yaml is not None:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}

        report_data = data.get("report", {}) or {}
        # Env toggles win over YAML so CI/cron can enable delivery via secrets
        # without committing a config.yaml.
        report = ReportConfig(
            output_dir=report_data.get("output_dir", "out"),
            to_file=_envbool("REPORT_TO_FILE", report_data.get("to_file", True)),
            to_email=_envbool("REPORT_TO_EMAIL", report_data.get("to_email", False)),
            to_telegram=_envbool("REPORT_TO_TELEGRAM", report_data.get("to_telegram", False)),
            to_discord=_envbool("REPORT_TO_DISCORD", report_data.get("to_discord", False)),
            smtp_host=_env("SMTP_HOST"),
            smtp_port=int(_env("SMTP_PORT") or 587),
            smtp_user=_env("SMTP_USER"),
            smtp_pass=_env("SMTP_PASS"),
            email_to=_env("REPORT_EMAIL") or report_data.get("email_to"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            discord_webhook_url=_env("DISCORD_WEBHOOK_URL"),
        )

        return cls(
            discord_bot_token=_env("DISCORD_BOT_TOKEN"),
            channel_id=_env("DISCORD_CHANNEL_ID") or _str(data.get("channel_id")),
            channel_name=data.get("channel_name", "stocks"),
            lookback_hours=int(data.get("lookback_hours", 24)),
            extractor_backend=_env("EXTRACTOR_BACKEND") or data.get("extractor_backend", "auto"),
            gemini_api_key=_env("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            gemini_model=data.get("gemini_model", "gemini-2.5-flash"),
            ollama_host=_env("OLLAMA_HOST") or data.get("ollama_host", "http://localhost:11434"),
            ollama_model=_env("OLLAMA_MODEL") or data.get("ollama_model", "qwen2.5:3b"),
            ollama_timeout=int(data.get("ollama_timeout", 180)),
            anonymize_usernames=data.get("anonymize_usernames", True),
            min_confidence=float(data.get("min_confidence", 0.35)),
            db_path=_env("DIGEST_DB") or data.get("db_path", "data/digest.db"),
            use_db=_envbool("USE_DB", data.get("use_db", True)),
            momentum_baseline_days=int(data.get("momentum_baseline_days", 7)),
            momentum_threshold=float(data.get("momentum_threshold", 2.0)),
            trusted_users={str(k): float(v) for k, v in (data.get("trusted_users", {}) or {}).items()},
            default_user_weight=float(data.get("default_user_weight", 1.0)),
            trusted_threshold=float(data.get("trusted_threshold", 2.0)),
            top_n=int(data.get("top_n", 10)),
            breaking_news_threshold=float(data.get("breaking_news_threshold", 0.6)),
            recency_half_life_hours=float(data.get("recency_half_life_hours", 12.0)),
            use_market_data=data.get("use_market_data", True),
            report=report,
        )

    # ------------------------------------------------------------------
    def weight_for(self, author_name: str, author_id: str = "") -> float:
        """Look up a user's trust weight (name or id), else default."""
        tu = self.trusted_users
        for key in (author_name, author_id, author_name.lower()):
            if key in tu:
                return tu[key]
        # case-insensitive fallback
        low = author_name.lower()
        for k, v in tu.items():
            if k.lower() == low:
                return v
        return self.default_user_weight


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)
