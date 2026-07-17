# Getting the bot added (for a channel you don't own)

You are a **member**, not the owner, so you cannot add a bot yourself —
Discord requires the **Manage Server** permission to authorise one. This is
the only Terms-of-Service-compliant way to read a channel. Here's the whole
ask, ready to send.

## 1. Create the bot (you do this, ~5 min)

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. Open the **Bot** tab → **Reset Token** → copy it into `.env` as
   `DISCORD_BOT_TOKEN`.
3. On the same Bot tab, scroll to **Privileged Gateway Intents** and turn on
   **Message Content Intent**. (Free and instant while the server has fewer
   than 10,000 members — no application needed.)
4. Open **OAuth2 → URL Generator**. Tick scope **`bot`**, then under Bot
   Permissions tick only **View Channels** and **Read Message History**.
   Copy the generated invite URL.

## 2. Message to send the server owner / a mod

> Hey! I'm building a **read-only** daily summary of our #stocks discussions
> (a "what stocks did people talk about today" digest — no posting, no DMs,
> no moderation). Could you add my bot with this link? It only needs **View
> Channel** + **Read Message History**, nothing else, and I'll restrict it to
> just the #stocks channel.
>
> Invite link: `PASTE_YOUR_OAUTH2_URL_HERE`
>
> Happy to show you exactly what it does first. Thanks! 🙏

## 3. After it's added

- Ask them to make sure the bot's role can **see** the target channel (channel
  settings → Permissions → add the bot's role with View Channel + Read Message
  History if the channel is private).
- Enable **Developer Mode** in your Discord (Settings → Advanced), right-click
  the channel → **Copy Channel ID**, and put it in `.env` as
  `DISCORD_CHANNEL_ID`.
- Run `python main.py --once` to pull the last 24h and generate a digest.

## What NOT to do

Do **not** use a "self-bot" or run an exporter with your **personal** account
token to get around needing the owner. That automates a user account, which is
an explicit Discord ToS violation and risks **permanent termination of your
account** (enforcement increased through 2025–2026). If the owner won't add a
bot, the ethical answer is: this feature isn't available on that server.
