"""Stage 7 — render and deliver the daily digest.

Renders Markdown (for Telegram/Discord/console) and a self-contained,
theme-aware HTML file (for email / archiving). Delivery channels are all
optional; writing to a file always works.
"""
from __future__ import annotations

import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .config import Config
from .models import DailyDigest, StockDigestItem

_SENT_EMOJI = {"positive": "🟢", "negative": "🔴", "mixed": "🟡"}
_PERF = {
    "doing_well": "📈 doing well",
    "doing_badly": "📉 doing badly",
    "mixed": "➖ mixed",
    "unknown": "",
}
_HYPE = {"hyped": "🔥 hyped", "quiet": "💤 quiet", "normal": "", "unknown": ""}


# =========================================================================
# Markdown
# =========================================================================
def render_markdown(d: DailyDigest) -> str:
    lines = [
        f"# 📊 Stock Chat Digest — #{d.channel_name}",
        f"*{d.report_date:%A, %d %b %Y}*",
        "",
        f"> {d.analyzed_messages} relevant of {d.total_messages} messages · "
        f"{len(d.items)} stocks surfaced · extractor: `{d.extractor}`",
        "",
    ]
    if not d.items:
        lines.append("_No stocks were discussed in a meaningful way today._")
        return "\n".join(lines)

    for i, item in enumerate(d.items, 1):
        lines.extend(_md_item(i, item))
    lines += [
        "",
        "---",
        "_Summary of community chatter, not investment advice. "
        "Verify independently before acting._",
    ]
    return "\n".join(lines)


def _md_item(rank: int, item: StockDigestItem) -> list[str]:
    emoji = _SENT_EMOJI.get(item.sentiment_label, "🟡")
    head = f"## {rank}. {emoji} {item.company} (`{item.canonical_symbol}`)"
    meta = (
        f"**{item.mention_count}** mentions · **{item.distinct_authors}** people · "
        f"consensus: **{item.consensus_recommendation.upper()}** · "
        f"sentiment: {item.sentiment_label} ({item.net_sentiment:+.2f})"
    )
    lines = [head, meta, f"_why surfaced: {item.surfaced_reason}_", ""]

    if item.market and item.market.price is not None:
        m = item.market
        bits = [f"₹/$ {m.price}"]
        if m.change_1d_pct is not None:
            bits.append(f"1d {m.change_1d_pct:+.1f}%")
        if m.change_5d_pct is not None:
            bits.append(f"5d {m.change_5d_pct:+.1f}%")
        if m.volume_ratio is not None:
            bits.append(f"vol {m.volume_ratio:.1f}×")
        tag = " ".join(x for x in (_PERF.get(m.performance_flag, ""), _HYPE.get(m.hype_flag, "")) if x)
        lines.append(f"**Market:** {' · '.join(bits)} {(' · ' + tag) if tag else ''}")
        lines.append("")

    if item.event_flags:
        lines.append(f"**⚡ Events:** {', '.join(item.event_flags)}")
        lines.append("")
    if item.positives:
        lines.append("**👍 Positives**")
        lines += [f"- {p}" for p in item.positives]
        lines.append("")
    if item.negatives:
        lines.append("**👎 Negatives**")
        lines += [f"- {n}" for n in item.negatives]
        lines.append("")
    if item.key_points:
        lines.append("**📝 Key points**")
        lines += [f"- {k}" for k in item.key_points]
        lines.append("")
    if item.trusted_stances:
        lines.append("**⭐ Trusted voices**")
        for t in item.trusted_stances:
            lines.append(
                f"- {t.author_name} ({t.recommendation}/{t.sentiment}): {t.quote}"
            )
        lines.append("")
    return lines


# =========================================================================
# HTML (self-contained, theme-aware)
# =========================================================================
def render_html(d: DailyDigest) -> str:
    cards = "\n".join(_html_item(i, it) for i, it in enumerate(d.items, 1))
    if not d.items:
        cards = "<p class='empty'>No stocks were discussed meaningfully today.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Chat Digest — {html.escape(d.channel_name)} — {d.report_date:%d %b %Y}</title>
<style>{_CSS}</style></head>
<body>
<header>
  <h1>📊 Stock Chat Digest</h1>
  <p class="sub">#{html.escape(d.channel_name)} · {d.report_date:%A, %d %b %Y}</p>
  <p class="stats">{d.analyzed_messages} relevant of {d.total_messages} messages ·
     {len(d.items)} stocks surfaced · extractor: {html.escape(d.extractor)}</p>
</header>
<main>{cards}</main>
<footer>Summary of community chatter, not investment advice. Verify independently before acting.</footer>
</body></html>"""


def _html_item(rank: int, item: StockDigestItem) -> str:
    e = html.escape
    cls = {"positive": "pos", "negative": "neg", "mixed": "mix"}[item.sentiment_label]
    market = ""
    if item.market and item.market.price is not None:
        m = item.market
        chips = []
        for label, val in (("1d", m.change_1d_pct), ("5d", m.change_5d_pct), ("1mo", m.change_1mo_pct)):
            if val is not None:
                c = "up" if val >= 0 else "down"
                chips.append(f"<span class='chip {c}'>{label} {val:+.1f}%</span>")
        if m.volume_ratio is not None:
            chips.append(f"<span class='chip'>vol {m.volume_ratio:.1f}×</span>")
        if m.hype_flag == "hyped":
            chips.append("<span class='chip hot'>🔥 hyped</span>")
        market = f"<div class='market'>{''.join(chips)}</div>"

    def block(title, rows, klass=""):
        if not rows:
            return ""
        lis = "".join(f"<li>{e(r)}</li>" for r in rows)
        return f"<div class='blk {klass}'><h4>{title}</h4><ul>{lis}</ul></div>"

    events = ""
    if item.event_flags:
        events = "<div class='events'>⚡ " + ", ".join(e(x) for x in item.event_flags) + "</div>"

    trusted = ""
    if item.trusted_stances:
        rows = "".join(
            f"<li><b>{e(t.author_name)}</b> "
            f"<span class='tag'>{e(t.recommendation)}/{e(t.sentiment)}</span> {e(t.quote)}</li>"
            for t in item.trusted_stances
        )
        trusted = f"<div class='blk trusted'><h4>⭐ Trusted voices</h4><ul>{rows}</ul></div>"

    return f"""
<article class="card {cls}">
  <div class="cardhead">
    <span class="rank">#{rank}</span>
    <h3>{e(item.company)} <code>{e(item.canonical_symbol)}</code></h3>
    <span class="rec">{e(item.consensus_recommendation.upper())}</span>
  </div>
  <div class="metrics">
    <span>{item.mention_count} mentions</span>
    <span>{item.distinct_authors} people</span>
    <span>sentiment {item.net_sentiment:+.2f}</span>
    <span class="reason">{e(item.surfaced_reason)}</span>
  </div>
  {market}{events}
  {block('👍 Positives', item.positives, 'pos')}
  {block('👎 Negatives', item.negatives, 'neg')}
  {block('📝 Key points', item.key_points)}
  {trusted}
</article>"""


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d21;--mut:#5b6570;--line:#e3e6ea;
--pos:#128a3b;--neg:#c62828;--mix:#b58100;--accent:#4b6ef5;--hot:#e8590c;}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--fg:#e6e9ee;
--mut:#9aa4b0;--line:#262b33;--pos:#4ade80;--neg:#f87171;--mix:#fbbf24;--accent:#7c9cff;--hot:#ff922b;}}
:root[data-theme=dark]{--bg:#0f1115;--card:#181b21;--fg:#e6e9ee;--mut:#9aa4b0;--line:#262b33;
--pos:#4ade80;--neg:#f87171;--mix:#fbbf24;--accent:#7c9cff;--hot:#ff922b;}
:root[data-theme=light]{--bg:#f6f7f9;--card:#fff;--fg:#1a1d21;--mut:#5b6570;--line:#e3e6ea;
--pos:#128a3b;--neg:#c62828;--mix:#b58100;--accent:#4b6ef5;--hot:#e8590c;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:24px}
header{max-width:820px;margin:0 auto 20px}h1{margin:0;font-size:26px}
.sub{color:var(--mut);margin:4px 0 2px;font-weight:600}.stats{color:var(--mut);font-size:13px;margin:0}
main{max-width:820px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mix);
border-radius:12px;padding:16px 18px}
.card.pos{border-left-color:var(--pos)}.card.neg{border-left-color:var(--neg)}.card.mix{border-left-color:var(--mix)}
.cardhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.cardhead h3{margin:0;font-size:18px;flex:1}code{background:rgba(127,127,127,.15);
padding:1px 6px;border-radius:5px;font-size:13px}
.rank{color:var(--mut);font-weight:700}.rec{background:var(--accent);color:#fff;
padding:2px 10px;border-radius:20px;font-size:12px;font-weight:700}
.metrics{display:flex;gap:14px;flex-wrap:wrap;color:var(--mut);font-size:13px;margin:8px 0}
.metrics .reason{margin-left:auto;font-style:italic}
.market{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.chip{background:rgba(127,127,127,.14);padding:2px 8px;border-radius:6px;font-size:12px}
.chip.up{color:var(--pos)}.chip.down{color:var(--neg)}.chip.hot{color:var(--hot);font-weight:700}
.events{color:var(--hot);font-size:13px;font-weight:600;margin:6px 0}
.blk{margin:8px 0}.blk h4{margin:0 0 4px;font-size:13px;text-transform:uppercase;
letter-spacing:.04em;color:var(--mut)}
.blk ul{margin:0;padding-left:18px}.blk li{margin:2px 0}
.blk.pos h4{color:var(--pos)}.blk.neg h4{color:var(--neg)}
.tag{background:rgba(127,127,127,.15);padding:0 6px;border-radius:5px;font-size:11px}
footer{max-width:820px;margin:22px auto 0;color:var(--mut);font-size:12px;text-align:center}
.empty{color:var(--mut);text-align:center;padding:40px}
"""


# =========================================================================
# Delivery
# =========================================================================
def write_files(d: DailyDigest, config: Config) -> dict[str, str]:
    out_dir = Path(config.report.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"digest_{d.report_date:%Y%m%d}"
    md_path = out_dir / f"{stem}.md"
    html_path = out_dir / f"{stem}.html"
    md_path.write_text(render_markdown(d), encoding="utf-8")
    html_path.write_text(render_html(d), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def send_email(d: DailyDigest, config: Config) -> bool:
    r = config.report
    if not (r.smtp_host and r.smtp_user and r.smtp_pass and r.email_to):
        print("[report] email not configured; skipping")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Stock Chat Digest — {d.report_date:%d %b %Y}"
    msg["From"] = r.smtp_user
    msg["To"] = r.email_to
    msg.attach(MIMEText(render_markdown(d), "plain", "utf-8"))
    msg.attach(MIMEText(render_html(d), "html", "utf-8"))
    with smtplib.SMTP(r.smtp_host, r.smtp_port) as s:
        s.starttls()
        s.login(r.smtp_user, r.smtp_pass)
        s.sendmail(r.smtp_user, [r.email_to], msg.as_string())
    print(f"[report] emailed to {r.email_to}")
    return True


def send_telegram(d: DailyDigest, config: Config) -> bool:
    r = config.report
    if not (r.telegram_bot_token and r.telegram_chat_id):
        print("[report] telegram not configured; skipping")
        return False
    import requests  # local import keeps offline runs dependency-free

    text = render_markdown(d)
    url = f"https://api.telegram.org/bot{r.telegram_bot_token}/sendMessage"
    ok = True
    for chunk in _chunks(text, 3800):
        resp = requests.post(
            url,
            json={"chat_id": r.telegram_chat_id, "text": chunk, "parse_mode": "Markdown"},
            timeout=30,
        )
        ok = ok and resp.ok
    print("[report] telegram sent" if ok else "[report] telegram failed")
    return ok


def send_discord(d: DailyDigest, config: Config) -> bool:
    r = config.report
    if not r.discord_webhook_url:
        print("[report] discord webhook not configured; skipping")
        return False
    import requests

    text = render_markdown(d)
    ok = True
    for chunk in _chunks(text, 1900):
        resp = requests.post(r.discord_webhook_url, json={"content": chunk}, timeout=30)
        ok = ok and resp.status_code in (200, 204)
    print("[report] discord webhook sent" if ok else "[report] discord webhook failed")
    return ok


def deliver(d: DailyDigest, config: Config) -> dict[str, str]:
    paths = {}
    if config.report.to_file:
        paths = write_files(d, config)
    if config.report.to_email:
        send_email(d, config)
    if config.report.to_telegram:
        send_telegram(d, config)
    if config.report.to_discord:
        send_discord(d, config)
    return paths


def _chunks(text: str, size: int):
    lines = text.split("\n")
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > size:
            if buf:
                yield buf
            buf = ln
        else:
            buf = f"{buf}\n{ln}" if buf else ln
    if buf:
        yield buf
