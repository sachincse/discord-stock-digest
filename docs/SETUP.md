# Setup Guide

From zero to a daily digest. Follow top to bottom — each step is copy-paste and
shows the expected result so you can check yourself.

**Contents**
1. [Prerequisites](#1-prerequisites)
2. [30-second offline test (no keys)](#2-30-second-offline-test-no-keys)
3. [Create the Discord bot](#3-create-the-discord-bot)
4. [Get it added to the server](#4-get-it-added-to-the-server)
5. [Get a free Gemini key](#5-get-a-free-gemini-key)
6. [Configure `.env` and `config.yaml`](#6-configure-env-and-configyaml)
7. [Run it](#7-run-it)
8. [Deploy for free (runs daily by itself)](#8-deploy-for-free-runs-daily-by-itself)
9. [Troubleshooting](#9-troubleshooting)
10. [Cost & privacy](#10-cost--privacy)

---

## 1. Prerequisites

- **Python 3.10+** and **git**
- A **Discord account**
- The **stocks channel** you want to read, in a server where **you or a mod has
  "Manage Server"** (needed once, to add the bot — you cannot add it as a plain
  member; see step 4)
- ~10 minutes

```bash
python --version      # expect 3.10 or higher
git --version
```

---

## 2. 30-second offline test (no keys)

Prove it works before configuring anything. This uses bundled sample chat and a
stub market provider — **no Discord, no Gemini, no keys**.

```bash
git clone https://github.com/sachincse/discord-stock-digest
cd discord-stock-digest
pip install -r requirements.txt
python main.py --selftest
```

Expected: a ranked table printed to the console and files written to `out/`:

```
  Digest for #stocks — 2026-07-17
  20/27 messages analysed · extractor=heuristic
============================================================
   1. Reliance Industries   RELIANCE.NS  BUY    ... — top consensus + breaking news
   ...
[selftest] OK
```

Open `out/digest_20260717.html` in a browser to see the rendered report.

---

## 3. Create the Discord bot

> You do this part (≈5 min). Reading a channel is only ToS-compliant via an
> official bot.

1. Go to <https://discord.com/developers/applications> → **New Application** →
   name it (e.g. "Stock Digest") → **Create**.
2. Left sidebar → **Bot**.
3. Click **Reset Token** → **Copy**. This is your `DISCORD_BOT_TOKEN` — paste it
   somewhere safe now (you can't view it again).
4. Scroll to **Privileged Gateway Intents** → turn **Message Content Intent**
   **ON** → **Save Changes**.

   > ⚠️ **This is the #1 setup mistake.** Without Message Content Intent the bot
   > connects fine but every `message.content` comes back **empty**, so your
   > digest is blank. This project already sets `intents.message_content = True`
   > in code — you must *also* enable the toggle here. (Free & instant while the
   > server has < 10,000 members.)

5. Left sidebar → **OAuth2** → **URL Generator**:
   - **Scopes:** tick **`bot`**
   - **Bot Permissions:** tick **View Channels** and **Read Message History**
     only (least privilege — never Administrator)
   - Copy the **Generated URL** at the bottom.

---

## 4. Get it added to the server

If **you** have Manage Server: open the copied URL, pick the server, **Authorize**.

If you **don't** own/manage the server: send the owner/a mod the copy-paste
message in **[owner_message.md](owner_message.md)** with your invite URL. A
regular member cannot add a bot — this is enforced by Discord.

Then get the **channel ID**: Discord → **Settings → Advanced → Developer Mode
ON** → right-click the channel → **Copy Channel ID**. That's your
`DISCORD_CHANNEL_ID`.

---

## 5. Get a free Gemini key

1. Go to <https://aistudio.google.com/apikey> → **Create API key**.
2. Copy it — that's your `GEMINI_API_KEY`.
3. **Keep billing disabled** on the project to stay on the free tier (Gemini
   2.5 Flash / Flash-Lite: 1M context, ~1,000 requests/day — a daily digest is
   one request).

> Skipping Gemini? The tool automatically falls back to the offline heuristic
> extractor. Lower quality, but zero keys and zero cost.

---

## 6. Configure `.env` and `config.yaml`

```bash
cp .env.example .env                 # secrets
cp config.example.yaml config.yaml   # tuning
```

Edit `.env` — every variable, where to get it, and whether it's required:

| Variable | Required? | Where to get it |
|---|---|---|
| `DISCORD_BOT_TOKEN` | for live runs | Developer Portal → Bot → Reset Token (step 3) |
| `DISCORD_CHANNEL_ID` | for live runs | right-click channel → Copy Channel ID (step 4) |
| `GEMINI_API_KEY` | recommended | <https://aistudio.google.com/apikey> (step 5) |
| `SMTP_HOST/USER/PASS`, `REPORT_EMAIL` | optional | your email provider (for email delivery) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional | @BotFather / your chat |
| `DISCORD_WEBHOOK_URL` | optional | Channel → Edit → Integrations → Webhooks |

Then edit `config.yaml` — set your **trusted users** (higher weight = counts for
more), `top_n`, and which delivery channels to enable. See
[config.example.yaml](../config.example.yaml) for every option.

> 🔒 `.env` and `config.yaml` are gitignored from the first commit. **Never
> commit your token.** If one leaks, hit **Reset Token** in the portal
> immediately — it's a password.

---

## 7. Run it

```bash
# One live run: pull the last 24h, use real market data, print + write report
python main.py --once --live-market

# Analyse an exported JSON instead of connecting live
python main.py --from-json data/export.json --live-market

# Run daily at 21:30 local time (keeps the process alive)
python main.py --schedule --at 21:30
```

Expected console output starts with:

```
[once] fetching last 24h from channel 123456789...
[once] fetched 214 messages
```

and ends with the ranked table + the paths of the written report files.

---

## 8. Deploy for free (runs daily by itself)

**Recommended: GitHub Actions + a Discord webhook.** Nothing to host, genuinely
free, and the schedule is one line. The workflow is already in
[.github/workflows/daily.yml](../.github/workflows/daily.yml).

1. Push your fork to GitHub.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**,
   add these (values only — never in code):

   | Secret | Value |
   |---|---|
   | `DISCORD_BOT_TOKEN` | your bot token |
   | `DISCORD_CHANNEL_ID` | the channel to read |
   | `GEMINI_API_KEY` | your Gemini key |
   | `DISCORD_WEBHOOK_URL` | webhook of the channel to post the digest into |

3. The workflow runs at **15:30 UTC daily** (= 21:00 IST). Change the `cron:` in
   `daily.yml` — validate expressions at <https://crontab.guru> (it's **UTC**).
4. Test it now without waiting: repo → **Actions → daily-digest → Run workflow**
   (the `workflow_dispatch` trigger).
5. Confirm it ran: **Actions** tab → open the run → check logs, and look for the
   digest posted to your Discord channel. Each run also uploads the report files
   as a downloadable artifact.

> ⚠️ **Gotchas:** GitHub silently **disables scheduled workflows after 60 days**
> of repo inactivity (a monthly commit or manual run keeps it alive), and cron
> runs can be **delayed 5–30 min** at peak — fine for a daily digest.

<details>
<summary>Alternative: run locally on Windows (Task Scheduler)</summary>

1. Create `run_digest.bat`:
   ```bat
   cd /d C:\path\to\discord-stock-digest
   python main.py --once --live-market
   ```
2. Task Scheduler → **Create Task** → Trigger: **Daily** at your time.
3. Action: **Start a program** → your `.bat`. Set **Start in** to the project
   folder.
4. In **Conditions**, uncheck "Start only if on AC power"; in **Settings**,
   check "Run task as soon as possible after a missed start".

Note: this only fires while your PC is on — GitHub Actions doesn't have that
limitation.
</details>

---

## 9. Troubleshooting

| Symptom / error | Cause → fix |
|---|---|
| Digest is **empty** / 0 stock messages | **Message Content Intent** not enabled in the Developer Portal (step 3.4). Enable it and re-run. |
| `PrivilegedIntentsRequired` | Same as above — the intent toggle is off in the portal. |
| `LoginFailure` / 401 | Wrong or stale `DISCORD_BOT_TOKEN`. Reset it in the portal, update `.env`, don't add quotes. |
| `[once] fetched 0 messages` | Wrong `DISCORD_CHANNEL_ID`, bot can't see the channel, or nothing posted in the last `lookback_hours`. Check the bot's role has View Channel + Read Message History on that channel. |
| Bot online but ignores the channel | Its role lacks channel access — a server admin must grant View Channel + Read Message History. |
| `ModuleNotFoundError` | Dependencies not installed / wrong venv. Re-run `pip install -r requirements.txt`. |
| yfinance `429 Too Many Requests` | Yahoo throttling. The tool already batches + degrades gracefully; just re-run later, or drop `--live-market`. |
| Gemini `429` / quota | Free-tier daily cap hit. Wait for reset (midnight Pacific) or switch `gemini_model` to `gemini-2.5-flash-lite`. |
| Scheduled workflow stopped firing | GitHub auto-disabled it after 60 days idle. Push a commit or run it manually to re-enable. |

---

## 10. Cost & privacy

- **Cost:** effectively **₹0/day** on free tiers. If you overflow to paid
  Gemini, a daily summary is ~a cent or two (2.5 Flash-Lite ≈ $0.10/1M in).
- **Privacy:** on Gemini's **free tier Google may use inputs to improve its
  products**. This tool sets `anonymize_usernames: true` (real names → `user1`,
  `user2`… before anything is sent). For fully private handling, use Gemini's
  cheap **paid** tier, which is not used for training.
- **Disclaimer:** the digest summarises **community chatter, not investment
  advice**, and sentiment can be wrong. Every report carries this notice.
