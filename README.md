# Shortlink Bypass Bot

A lightweight Telegram bot that bypasses link shorteners, built for **Render Free Tier** + **UptimeRobot** keep-alive.

## What it supports

- **Safelink-script family** (generic walker): `vplink.in`, `arolinks.com`, `gplinks`, `droplink`, `tnshort.net`, `rslinks.net`, `xpshort.com`, `earnl.xyz`, `adrinolinks.in`, `krownlinks.me`, `du-link.in`, `onepagelink.in`
- **Linkvertise** (best-effort JSON/base64 target extraction)
- **Generic shorteners** (`bit.ly`, `tinyurl`, `cutt.ly`, …) via redirect-following

## Deploy on Render (Free)

1. Create a bot with [@BotFather](https://t.me/BotFather) → copy the token.
2. Push this repo to GitHub, then on Render: **New → Web Service → connect repo**.
3. Settings:
   - **Runtime:** Python 3.12
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
4. Environment variables:
   - `BOT_TOKEN` = your BotFather token
   - `PORT` is set by Render automatically — no need to add it.
5. Deploy. The Flask server answers Render's health checks on `/` and `/health`.

## Keep it awake 24/7 with UptimeRobot

1. UptimeRobot → **Add New Monitor** → type **HTTP(s)**.
2. URL: `https://<your-service>.onrender.com/health`
3. Interval: **5 minutes**. The bot's Flask endpoint responds, preventing Render's free-tier spin-down.

## Known limitations

- `vplink.in` / `arolinks.com` run a VPN/proxy check; datacenter IPs (Render's) can occasionally be served the "disable VPN" interstitial. Retry usually helps. If it becomes systematic, a residential proxy or a site-specific update is needed.
- Shortener sites change layouts often. When a site breaks, the fix belongs in `adapters.py` (add a dedicated function and register it in `ADAPTERS`).

## Files

| File | Purpose |
|---|---|
| `main.py` | Telegram bot + Flask keep-alive server (single process) |
| `resolver.py` | Routes a URL to the right adapter or the generic resolver |
| `adapters.py` | Site-specific bypass logic (edit here when a site breaks) |
| `requirements.txt` / `runtime.txt` / `Procfile` | Render/deployment config |
