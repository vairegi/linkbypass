import asyncio
import logging
import os
import threading

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from resolver import resolve_link

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bypassbot")

BOT_TOKEN = os.environ["BOT_TOKEN"]  # from @BotFather
PORT = int(os.environ.get("PORT", "10000"))  # Render injects PORT automatically

# ---------------------------------------------------------------------------
# Flask keep-alive server: answers Render health checks AND UptimeRobot pings
# ---------------------------------------------------------------------------
web = Flask(__name__)


@web.get("/")
def index():
    return "Shortlink Bypass Bot is running.", 200


@web.get("/health")
def health():
    return {"status": "ok"}, 200


def run_web():
    web.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------
HELP = (
    "Send me any shortlink and I'll try to bypass it.\n\n"
    "Site families: vplink.in, arolinks.com (browser bypass), gplinks, droplink, "
    "ouo.io, linkvertise, plus generic shorteners (bit.ly, tinyurl, cutt.ly, ...).\n\n"
    "Note: vplink/arolinks have a VPN check — if it fails, the admin must set PROXY_URL."
)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a shortlink to bypass.\n\n" + HELP)


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        await update.message.reply_text("That doesn't look like a link. Send a full URL starting with https://")
        return
    msg = await update.message.reply_text("⏳ Bypassing… browser-based sites can take ~30–60s.")
    try:
        result = await asyncio.to_thread(resolve_link, text)
        await msg.edit_text(f"✅ Bypassed:\n{result}")
    except Exception as e:
        log.exception("bypass failed for %s", text)
        await msg.edit_text(f"❌ Couldn't bypass this link.\nReason: {e}")


def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    log.info("Bot started, web keep-alive on port %s", PORT)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
