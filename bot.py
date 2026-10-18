"""
Don Escrow Service bot - single file.

Sirf 2 files: bot.py + requirements.txt

1) Neeche CONFIG mein values paste karo (ya hosting ke Variables mein daalo).
2) Session string nikalne ke liye (ek baar, apne computer par):  python bot.py session
3) Bot chalane ke liye:  python bot.py
"""
import os
import sys
import asyncio
import time
import html
import uuid
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)
from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

logging.basicConfig(level=logging.INFO)

# ======================= CONFIG =======================
def cfg(name: str, default: str = "") -> str:
    """Pehle hosting Variable dekhta hai, nahi mila to neeche likhi value."""
    return (os.getenv(name) or default).strip()


# Yahan quotes ke andar values paste kar sakte ho:
BOT_TOKEN = cfg("BOT_TOKEN", "8684366725:AAGIAPh7HeTpr1jlSjhF6IQeapg7s4xPXF8")          # BotFather se token
API_ID = cfg("API_ID", "34145046")                # my.telegram.org se (sirf number)
API_HASH = cfg("API_HASH", "9eef1f689e6bde55fa0240660f7222ca")            # my.telegram.org se
USERBOT_SESSION = cfg("USERBOT_SESSION", "1AZWarzQBuynh2jMmOumHufr10ekAqgnZ7hkNjzdxxIhbsNAl5y5u0HDd9p0_XcUJi295fuKnmXE7jZqV2rmwikZaDlsLOINBIBxegsDGpsZZ8QLc5Q0FWeC8W32VibhyAkqsMLarxxdCHkYJDkqppUPq-y0jNWAxOBHBGTdkqE9WhPjAq7ZCbyB5k9F4GHsxPDIyuo0TWZ9pxtw8vTqrM3CAlzphHligzz2iAL76KCRml_h4-ygcWCEsOI93ukfZ5BVtLmlEHKf8pvqB8GLuClCNuCQJpP3e47yLXd52c-ZwhKDqhN0F6kkR09zJ_s9zkTz9JFzZVe1y8Wp2_9w4DdKagZRDAuA=")  # python bot.py session se mili string
LOG_CHAT_ID = cfg("LOG_CHAT_ID", "")      # optional: naye deal ki info is chat mein
INVITE_LIMIT = int(cfg("INVITE_LIMIT", "1111"))  # ek link par max log
COOLDOWN = 60  # seconds, ek user ke do group ke beech

DEAL_TYPES = {"p2p": "P2P", "product": "Product Deal"}
HTML = ParseMode.HTML

# ======================= CUSTOM EMOJI =======================
# name -> (custom_emoji_id, fallback emoji). Naya emoji add karna ho to ek line jodo.
EMOJI = {
    "check":     ("5776375003280838798", "✅"),
    "cross":     ("5778527486270770928", "❌"),
    "link":      ("5877465816030515018", "🔗"),
    "shield":    ("5926783847453692661", "🛡"),
    "lock":      ("5832546462478635761", "🔒"),
    "unlock":    ("6034962180875490251", "🔓"),
    "key":       ("6005570495603282482", "🔑"),
    "user":      ("5771887475421090729", "👤"),
    "chat":      ("5886666250158870040", "💬"),
    "bot":       ("5931415565955503486", "🤖"),
    "warning":   ("5881702736843511327", "⚠️"),
    "alert":     ("5879813604068298387", "❗️"),
    "info":      ("5879785854284599288", "ℹ️"),
    "pin":       ("5908961403917570106", "📌"),
    "star":      ("5958376256788502078", "⭐️"),
    "fire":      ("6008118472066732010", "🔥"),
    "gift":      ("6032937473162614352", "🎁"),
    "party":     ("5994502837327892086", "🎉"),
    "cheers":    ("5967688845397855939", "🥂"),
    "phone":     ("5897567714674741148", "📞"),
    "support":   ("5906995262378741881", "🙋"),
    "briefcase": ("5967389567781703494", "💼"),
    "clock":     ("5776213190387961618", "🕓"),
    "chart":     ("5776219138917668486", "📈"),
    "tag":       ("5854776233950188167", "🏷"),
    "news":      ("5886506997066502636", "📰"),
    "globe":     ("5879585266426973039", "🌐"),
    "bolt":      ("5843553939672274145", "⚡️"),
    "thumbsup":  ("5992199545151295755", "👍"),
    "heart":     ("5994453058656931434", "❤️"),
    "search":    ("5874960879434338403", "🔎"),
    "file":      ("5839323457015256759", "📄"),
    "folder":    ("5875206779196935950", "📁"),
    "dice":      ("5960608239623082921", "🎲"),
    "plus":      ("5877219383691972108", "➕"),
    "arrow":     ("5877468380125990242", "➡️"),
}


def e(name: str) -> str:
    """Message text ke liye custom emoji (HTML)."""
    cid, fallback = EMOJI[name]
    return f'<tg-emoji emoji-id="{cid}">{fallback}</tg-emoji>'


def eid(name: str) -> str:
    """Button icon ke liye raw custom emoji id."""
    return EMOJI[name][0]


# ======================= USERBOT (group creator) =======================
# Telegram bots khud group nahi bana sakte, isliye ek dedicated user account use hota hai.
client = None  # main() mein banega


async def create_deal_group(bot_username: str, label: str):
    """Naya private group banata hai. Returns (bot_chat_id, invite_link, deal_id)."""
    deal_id = uuid.uuid4().hex[:6].upper()
    result = await client(CreateChannelRequest(
        title=f"{label} Deal #{deal_id}",
        about="Don Escrow Service - private deal group",
        megagroup=True,
    ))
    channel = result.chats[0]

    bot_entity = await client.get_entity(bot_username)
    await client(InviteToChannelRequest(channel, [bot_entity]))
    await client.edit_admin(
        channel, bot_entity,
        change_info=True, delete_messages=True, ban_users=True,
        invite_users=True, pin_messages=True,
    )

    invite = await client(ExportChatInviteRequest(channel, usage_limit=INVITE_LIMIT))
    return utils.get_peer_id(channel), invite.link, deal_id


# ======================= TEXTS =======================
def start_text() -> str:
    return (
        f"{e('party')} <b>Welcome to Don Escrow Service</b> {e('party')}\n\n"
        f"{e('shield')} Escrow : @xDonEscrow {e('check')}\n"
        f"{e('chat')} P2P Group : @PW_P2P {e('check')}\n"
        f"{e('info')} Detail : @BSR_ShoppiE {e('check')}\n"
        f"{e('support')} Customer help : @PW_AssistBot {e('check')}"
    )


def select_text() -> str:
    return f"{e('shield')} <b>Please select your escrow type from below.</b>"


# ======================= KEYBOARDS =======================
def btn(label, icon, icons, url=None, cb=None) -> InlineKeyboardButton:
    kw = {"api_kwargs": {"icon_custom_emoji_id": eid(icon)}} if icons else {}
    return InlineKeyboardButton(label, url=url, callback_data=cb, **kw)


def start_kb(icons: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("Escrow", "shield", icons, cb="escrow")],
        [btn("P2P Group", "chat", icons, url="https://t.me/PW_P2P")],
        [btn("Detail", "info", icons, url="https://t.me/BSR_ShoppiE")],
        [btn("Customer help", "support", icons, url="https://t.me/PW_AssistBot")],
    ])


def type_kb(icons: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        btn("P2P", "user", icons, cb="deal:p2p"),
        btn("Product Deal", "tag", icons, cb="deal:product"),
    ]])


async def render(send):
    """Pehle custom emoji icons ke saath try karo, fail ho to plain buttons."""
    for icons in (True, False):
        try:
            return await send(icons)
        except BadRequest as err:
            logging.warning("send failed (icons=%s): %s", icons, err)


# ======================= HANDLERS =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render(lambda icons: update.message.reply_text(
        start_text(), parse_mode=HTML, reply_markup=start_kb(icons),
        disable_web_page_preview=True,
    ))


async def escrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await render(lambda icons: q.message.reply_text(
        select_text(), parse_mode=HTML, reply_markup=type_kb(icons),
    ))


async def deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    label = DEAL_TYPES[q.data.split(":")[1]]

    if time.time() - context.user_data.get("last_deal", 0) < COOLDOWN:
        await q.answer("Please wait a minute before creating another group.", show_alert=True)
        return
    context.user_data["last_deal"] = time.time()

    await q.answer("Creating your group...")
    status = await q.message.reply_text(
        f"{e('clock')} Creating your <b>{label}</b> group, please wait...", parse_mode=HTML,
    )

    try:
        bot_username = (await context.bot.get_me()).username
        chat_id, link, deal_id = await create_deal_group(bot_username, label)
    except Exception:
        logging.exception("group creation failed")
        context.user_data["last_deal"] = 0
        await status.edit_text(
            f"{e('cross')} Group could not be created. Please try again or contact @PW_AssistBot.",
            parse_mode=HTML,
        )
        return

    await render(lambda icons: status.edit_text(
        f"{e('check')} <b>{label} group is ready!</b>\n\n"
        f"Join using the button below and add the other party.",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([[btn("Join Group", "link", icons, url=link)]]),
    ))

    mention = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'
    try:
        await context.bot.send_message(
            chat_id,
            f"{e('shield')} <b>{label} Deal #{deal_id}</b>\n\n"
            f"{e('user')} Created by: {mention}\n"
            f"{e('info')} Please add the other party and share the deal details here.",
            parse_mode=HTML,
        )
    except Exception:
        logging.exception("group welcome message failed")

    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(
                LOG_CHAT_ID,
                f"New {label} deal #{deal_id} by {mention} (id {user.id})\n{link}",
                parse_mode=HTML, disable_web_page_preview=True,
            )
        except Exception:
            logging.exception("log message failed")


async def post_init(app: Application):
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("USERBOT_SESSION invalid hai. gen_session.py dobara chalao.")
    logging.info("Userbot connected.")


async def post_shutdown(app: Application):
    await client.disconnect()


# ======================= MAIN =======================
async def make_session():
    """Userbot account login karke USERBOT_SESSION string print karta hai."""
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    c = TelegramClient(StringSession(), api_id, api_hash)
    await c.start()  # phone number aur OTP puchega
    print("\nUSERBOT_SESSION =", c.session.save())
    await c.disconnect()


def main():
    global client
    logging.info("=== Don Escrow bot v3 starting ===")

    if len(sys.argv) > 1 and sys.argv[1] == "session":
        asyncio.run(make_session())
        return

    missing = [
        name for name, val in [
            ("BOT_TOKEN", BOT_TOKEN), ("API_ID", API_ID),
            ("API_HASH", API_HASH), ("USERBOT_SESSION", USERBOT_SESSION),
        ] if not val
    ]
    if missing:
        sys.exit("Ye environment variables missing hain: " + ", ".join(missing))
    if not API_ID.isdigit():
        sys.exit("API_ID sirf number hona chahiye (jaise 12345678).")

    client = TelegramClient(StringSession(USERBOT_SESSION), int(API_ID), API_HASH)

    app = (
        Application.builder().token(BOT_TOKEN)
        .post_init(post_init).post_shutdown(post_shutdown).build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(escrow, pattern=r"^escrow$"))
    app.add_handler(CallbackQueryHandler(deal, pattern=r"^deal:(p2p|product)$"))
    app.run_polling()


if __name__ == "__main__":
    main()
