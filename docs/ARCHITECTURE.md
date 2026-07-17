# Architecture

## Design goal

Turn a day of noisy, interleaved, multi-person stock chat into a ranked,
attributed, evidence-backed digest — cheaply and (mostly) offline. The guiding
principle is a **hybrid split**:

> Deterministic heuristics do the bulk-reduction, structure, and math
> (fast, auditable, free). The LLM does only the fuzzy language work
> (disambiguation, point extraction, nuanced sentiment) on small, pre-filtered,
> grounded inputs.

This keeps LLM cost near zero, makes results reproducible, and means the tool
runs fully offline for development and testing.

## Pipeline

```
RawMessage[]                     ← ingest (bot / exported JSON / fixtures)
   │
   ▼  noise_filter.filter_messages
kept messages                    ← drop bots/greetings/emoji, KEEP anything
   │                               with a ticker or event keyword
   ▼  disentangle.build_threads
Thread[]                         ← reply edges + threads + @mentions +
   │                               shared-ticker/time heuristics (Union-Find)
   ▼  extract.Extractor
StockMention[]                   ← Heuristic (offline) OR Gemini (LLM);
   │                               every symbol validated vs the gazetteer
   ▼  market.MarketProvider
+ MarketSnapshot                 ← yfinance batch (or stub); hype/perf flags
   │
   ▼  aggregate.build_items
StockDigestItem[]                ← group per stock; trust + recency weighting
   │
   ▼  aggregate.rank  (dual-track)
ranked & surfaced items          ← Track A relevance ∪ Track B breaking-news
   │
   ▼  report.deliver
Markdown + HTML → file/email/telegram/discord
```

## Key modules

| Module | Responsibility |
|---|---|
| `models.py` | Frozen contracts (dataclasses) shared by every stage |
| `config.py` | Env (secrets) + YAML (tuning) loader; trust-weight lookup |
| `gazetteer.py` | Casual text → validated symbols; the anti-hallucination guardrail |
| `ingest.py` | JSON (DiscordChatExporter or simple) → `RawMessage[]` |
| `discord_bot.py` | Live, ToS-compliant ingestion via the official bot API |
| `noise_filter.py` | Stage 1 — cheap deterministic junk removal |
| `disentangle.py` | Stage 2 — conversation threading (Union-Find over signals) |
| `extract.py` | Stage 3 — `HeuristicExtractor` + `GeminiExtractor` |
| `market.py` | Stage 4 — `YFinanceProvider` + `StubMarketProvider` |
| `aggregate.py` | Stage 5+6 — per-stock aggregation + dual-track ranking |
| `report.py` | Stage 7 — Markdown/HTML render + delivery |
| `pipeline.py` | Wires the stages; pure and unit-testable |

## Why these choices

**Gazetteer-grounded extraction.** LLMs return valid-but-wrong JSON — they will
happily invent tickers. Both extractors are constrained to symbols that resolve
in `data/symbols.csv`, and the Gemini path re-validates every returned symbol.
"Valid JSON is not correct JSON."

**Disentanglement is mostly free.** Unlike IRC, Discord exposes explicit reply
edges, threads and @mentions, so threading is largely a graph
connected-components problem. We only fall back to heuristics
(shared-ticker-within-window, same-author bursts) for the residue.

**Dual-track ranking.** A single score can't satisfy both "surface what's
relevant for investment" and "don't miss big news". So:
- **Track A (relevance)** — trust-weighted consensus: who said it, how many
  people, how strongly, how substantively, recency-decayed.
- **Track B (breaking-news)** — deliberately *weight-agnostic*: a concrete
  event (order win, results, circuit, SEBI action) crosses the threshold on its
  own, so real news from an unknown/low-trust user is never dropped.
The surfaced set is `top-N(A) ∪ {items over B threshold}`.

**Trust weighting lives in code, not the prompt.** Author weights are applied
during aggregation, never fed to the LLM — this keeps extraction unbiased and
weighting auditable.

**Privacy by default.** On the free Gemini tier Google may train on inputs, so
`anonymize_usernames` replaces real names with `user1/user2…` before any text
leaves the machine, while still letting the model attribute stances per speaker.

## Extending

- **More symbols:** add rows to `data/symbols.csv` (`canonical_symbol,company,exchange,aliases`).
- **Swap the LLM:** implement the `Extractor` protocol (`name`, `extract`).
- **Swap market data:** implement the `MarketProvider` protocol (`name`, `fetch`).
- **New delivery channel:** add a `send_*` in `report.py` and call it from `deliver`.

## Limitations

- The heuristic extractor mis-handles multi-ticker single messages and sarcasm;
  use Gemini for production-quality sentiment.
- The gazetteer is a starter list; broaden it for full-market coverage.
- yfinance is unofficial and rate-limited — the provider degrades to `None`
  fields on failure rather than crashing the digest.
- Output is a summary of chatter, **not investment advice.**
