# Shortlink Bypass Bot

Lightweight Telegram bot that bypasses link shorteners, built for **Render Free Tier** + **UptimeRobot** keep-alive.

## What it supports

- **VPN-gated safelinks** — `vplink.in`, `arolinks.com` → real Chromium (Playwright) so the in-browser VPN check + timer actually run
- **Other safelink-family sites** (fast pure-HTTP walker): gplinks, droplink, tnshort.net, rslinks.net, xpshort.com, earnl.xyz, adrinolinks.in, krownlinks.me, du-link.in, onepagelink.in
- **Linkvertise** (best-effort JSON/base64 extraction)
- **Generic shorteners** (bit.ly, tinyurl, cutt.ly, …) via redirect-following

## Deploy on Render (Free)

1. [@BotFather](https://t.me/BotFather) → create bot → copy token.
2. Push repo to GitHub → Render → **New → Web Service** → connect repo.
3. Settings:
   - **Runtime:** Python 3.12
   - **Build Command:** `pip install -r requirements.txt && playwright install --with-deps chromium`
   - **Start Command:** `python main.py`
4. Env vars: `BOT_TOKEN` (required) · `PORT` (Render sets it) · `PROXY_URL` (optional, see below).
5. Flask answers health checks on `/` and `/health`.

## UptimeRobot (24/7)

UptimeRobot → **Add Monitor → HTTP(s)** → `https://<your-service>.onrender.com/health` → interval **5 min**.

## ⚠️ Important: the VPN check on vplink.in / arolinks.com

Both sites run a client-side VPN/proxy check. With a real browser (already included) it *can* pass,
**but datacenter IPs (Render's) are often still flagged**. If you see
"no destination appeared / VPN check" errors, set env var:

```
PROXY_URL = http://user:pass@your-residential-proxy:port
```

A residential or mobile proxy routes the browser through a home/mobile IP, which passes the check.
This is the reliable fix — cookies alone do NOT help (the gate is not a login wall).

## Maintenance

When a site changes, edit `adapters.py` (add/adjust an adapter, register it in `ADAPTERS`).
The Telegram error message names the failing hop.
