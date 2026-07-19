# No admin rights? Read this.

You're a **plain member** of the server — no "Manage Server" permission, and no
way to ask a mod to add a bot. That blocks the clean automated route (a bot must
be installed by someone with Manage Server). Here's the honest set of options,
ranked by **real risk**, not just the rulebook.

## ✅ The recommended path: manual copy‑paste (allowed, ~zero risk)

Reading messages you can already see and copying them is ordinary human use —
it's **not** scraping, **not** a bot, and gives Discord nothing to flag. For one
channel, once a day, it's a ~2‑minute step, and this tool ingests it directly.

**Steps**
1. Open the channel, select the day's messages, and copy them.
2. Paste into a plain text file, e.g. `today.txt`.
3. Run:
   ```bash
   python main.py --from-text today.txt --live-market
   ```

**Get better output (optional):** prefix lines with the author so trust‑weighting
works. All three of these are accepted (mix freely):
```
[Rajesh] RIL looking strong, accumulating.
Priya: Suzlon is risky, avoid the hype.
NVDA strong earnings, long term buy      <- no name: still counted, just unattributed
```
- `[Name] message` or `Name: message` → attributed to that user (enables trust
  weighting and "Trusted voices").
- A plain line → still analysed for stocks + sentiment, just not attributed.
- Timestamp lines ("Today at 10:32") are ignored automatically.

That's the whole thing. No keys needed for the offline extractor; add a Gemini
key or a local Ollama model for better sentiment (see [SETUP.md](SETUP.md)).

## 🥇 Still the best, if it ever becomes possible: the bot route

If you can *ever* get someone with Manage Server to add a read‑only bot (or you
join/create a server where you have rights), that's the ideal — fully automatic,
fully within ToS, and it can run daily by itself. The 5‑minute ask is in
[owner_message.md](owner_message.md).

## 🚫 What this project deliberately does NOT do

- **Browser userscript / DOM scraper** — a script that reads the web client and
  auto‑exports messages. Even a passive one is **against Discord's Terms of
  Service** (client modification + scraping), so it isn't shipped here.
- **User‑token export (DiscordChatExporter with your account token, self‑bots)** —
  this automates your personal account, which is a **ToS violation**, and as of
  2026 Discord actively detects and enforces it (instant logouts + warning
  emails, because the token's API traffic is fingerprinted server‑side). Using it
  risks **permanent loss of your Discord account**. Don't.

The manual path above exists precisely so you never need these.

> Summary of community chatter, not investment advice. And don't republish or
> monetise other people's messages — that's a separate ToS line.
