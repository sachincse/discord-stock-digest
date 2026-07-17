# Roadmap & prior art

This project was designed after surveying mature social-stock tools and Discord
summarizer bots. That research **validated the core design** (gazetteer-grounded
extraction, structured LLM output, provenance metadata, price enrichment,
disclaimers — all already implemented) and surfaced the improvements below.

## Prior art we learned from

| Project | What it does | What we borrowed |
|---|---|---|
| [SimplySummary](https://github.com/KenDingel/SimplySummary) | Discord summarizer that already emits tickers + prices + sentiment | Output schema (ticker + price + sentiment + events), embed/message splitting, "do your own research" disclaimer |
| [daily-discord-summarizer](https://github.com/rauljordan/daily-discord-summarizer) | Rust+SQLite periodic digest, map-reduce summarization | Two-stage map-reduce for long days; persist-first-then-summarize (roadmap) |
| [discord-tldr-bot](https://github.com/leofdgit/discord-tldr-bot) | `/tldr` + daily summaries | Model choice via config; explicit accuracy + privacy disclaimers; real cost anchor (~$0.10/200 msgs) |
| [Discord-AI-Summarizer](https://github.com/ThatSINEWAVE/Discord-AI-Summarizer) | On-demand channel summaries | Provenance stamp (# messages analysed + time window); role-gated trigger |
| [M3-org/discord-summarizer](https://github.com/M3-org/discord-summarizer) | Local Ollama, export-based, structured output | Token-compaction preprocessing; local-model fallback (roadmap) |
| [ApeWisdom](https://apewisdom.io/api/) / [SwaggyStocks](https://swaggystocks.com/dashboard/wallstreetbets/how-it-works) | Trending-ticker dashboards | Momentum = *change* in mentions vs baseline (not raw volume); mentions/velocity/sentiment quartet |
| [Alpha Scientist](https://alphascientist.com/reddit_part2.html) | WSB ticker ranking walkthrough | `pct_tickers` list-spam down-weighting (implemented); all-caps bare-ticker rule (implemented) |
| [wsbtickerbot](https://github.com/RyanElliott10/wsbtickerbot) / [pysentiment2](https://github.com/nickderobertis/pysentiment) | Regex→validate→blacklist; Loughran-McDonald lexicon | Programmatic collision blacklist; finance-specific sentiment lexicon (roadmap) |

## Already implemented

- ✅ Gazetteer-validated tickers (no hallucinations); `$cashtag` + alias support
- ✅ **All-caps rule** for short bare tickers + collision blacklist
- ✅ **List-spam (`pct_tickers`) down-weighting** of watchlist dumps
- ✅ Structured JSON output from Gemini (response schema)
- ✅ Conversation disentanglement from Discord reply/thread/@mention signals
- ✅ Noise/token compaction pre-filter (keeps ticker/event messages)
- ✅ **Negation- + emoji-aware** offline heuristic sentiment
- ✅ Dual-track ranking (trust-weighted consensus ∪ weight-agnostic breaking news)
- ✅ Trust + recency weighting; provenance metadata; yfinance price/volume/news
- ✅ Multi-channel delivery (file/email/Telegram/Discord); free GitHub Actions deploy
- ✅ Username anonymisation for the free LLM tier; "not advice" disclaimer

## Planned

| Idea | Why | Effort |
|---|---|---|
| **SQLite persistence + cross-day trends** | Persist per-symbol daily counts → "new tickers today", "rising vs 7-day avg", true mention-velocity/momentum for Track-B (the real "hyped" signal). Also enables dedup and backfills. | medium |
| **Map-reduce for very busy days** | Chunk → extract per chunk → merge, so a firehose day never silently truncates past the context budget. | medium |
| **Cost/rate-limit guardrails** | Per-run token logging, a daily $/token ceiling, `tenacity` retry+jitter on 429s. | medium |
| **Transformer extractor** (FinTwitBERT / roberta-StockTwits) | Offline, quota-free, social-media-tuned sentiment — a middle tier between heuristic and Gemini. Slots into the `Extractor` protocol. | medium |
| **VADER + Loughran-McDonald lexicon** | Upgrade offline sentiment with finance-correct polarity + intensifiers. | medium |
| **Auto-build full symbol universe** | `scripts/build_symbols.py` already fetches NSE; extend to BSE + richer aliases and cache. | low |
| **Dedicated hype score** | Rocket/moon emoji, ALL-CAPS ratio, "to the moon/multibagger" slang → Track-B only, kept separate from investment sentiment. | medium |
| **Hinglish routing** | Route code-mixed Indian chat to the LLM path; never trust English-tuned FinBERT/VADER on it. | low |
| **Crypto-collision guard** | Require stronger context for symbols that are also crypto tickers. | low |
| **Labeled eval set** | Use StockTwits self-labelled Bullish/Bearish tags as a regression benchmark to tune weights by measurement, not guesswork. | medium |
| **Local Ollama fallback** | Zero-cost, fully private extraction mode. | high |

Contributions welcome — pick any row and open a PR.
