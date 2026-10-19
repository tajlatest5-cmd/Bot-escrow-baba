"""
Don Escrow Service bot - single file.

Sirf 2 files: bot.py + requirements.txt

1) Neeche CONFIG mein values paste karo (ya hosting ke Variables mein daalo).
2) Session string nikalne ke liye (ek baar, apne computer par):  python bot.py session
3) Bot chalane ke liye:  python bot.py
"""
import os
import re
import sys
import asyncio
import time
import html
import uuid
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, ChatMigrated
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, PicklePersistence, filters,
)
from telethon import TelegramClient, utils, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CreateChannelRequest, InviteToChannelRequest, LeaveChannelRequest,
)
from telethon.tl.functions.messages import (
    CreateChatRequest, DeleteChatUserRequest, ExportChatInviteRequest,
)
from telethon.tl.types import InputUserSelf

logging.basicConfig(level=logging.INFO)
VERSION = "v17"

# ======================= CONFIG =======================
def cfg(name: str, default: str = "") -> str:
    """Pehle hosting Variable dekhta hai, nahi mila to neeche likhi value."""
    return (os.getenv(name) or default).strip()


# Yahan quotes ke andar values paste kar sakte ho:
BOT_TOKEN = cfg("BOT_TOKEN", "8684366725:AAGpZY0E1_0yia5l1l9GCXWdsvRO3L7KDwk")          # BotFather se token
API_ID = cfg("API_ID", "34145046")                # my.telegram.org se (sirf number)
API_HASH = cfg("API_HASH", "9eef1f689e6bde55fa0240660f7222ca")            # my.telegram.org se
USERBOT_SESSION = cfg("USERBOT_SESSION", "1AZWarzQBuynh2jMmOumHufr10ekAqgnZ7hkNjzdxxIhbsNAl5y5u0HDd9p0_XcUJi295fuKnmXE7jZqV2rmwikZaDlsLOINBIBxegsDGpsZZ8QLc5Q0FWeC8W32VibhyAkqsMLarxxdCHkYJDkqppUPq-y0jNWAxOBHBGTdkqE9WhPjAq7ZCbyB5k9F4GHsxPDIyuo0TWZ9pxtw8vTqrM3CAlzphHligzz2iAL76KCRml_h4-ygcWCEsOI93ukfZ5BVtLmlEHKf8pvqB8GLuClCNuCQJpP3e47yLXd52c-ZwhKDqhN0F6kkR09zJ_s9zkTz9JFzZVe1y8Wp2_9w4DdKagZRDAuA=")  # python bot.py session se mili string
LOG_CHAT_ID = cfg("LOG_CHAT_ID", "")      # optional: naye deal ki info is chat mein
_admin_raw = cfg("ADMIN_GROUP_ID", "-1004495890781")    # admin group ki ID (group mein /id likho to milegi)
ADMIN_GROUP_ID = int(_admin_raw) if re.fullmatch(r"-?\d+", _admin_raw) else None
INVITE_LIMIT = int(cfg("INVITE_LIMIT", "2"))  # ek link par max log (buyer + seller)
GROUP_MODE = cfg("GROUP_MODE", "basic")  # basic = owner (userbot) baad mein nikal sakta hai; super = supergroup
USERBOT_LEAVE = cfg("USERBOT_LEAVE", "1") == "1"  # buyer+seller aane ke baad userbot group chhod de
COOLDOWN = 60  # seconds, ek user ke do group ke beech
# Escrow ke username (comma se alag, @ ke bina). Ye group mein add hote hi form aata hai.
ESCROW_USERNAMES = {
    u.strip().lstrip("@").lower()
    for u in cfg("ESCROW_USERNAMES", "xDonEscrow").split(",") if u.strip()
}

DEAL_TYPES = {"p2p": "P2P", "product": "Product Deal"}

# ======= PAYMENT ADDRESSES =======
# Yahan apne wallet address quotes ke andar paste karo (ya Railway Variables mein ADDR_... daalo).
# Jis option ka address khaali chhodoge wo buttons mein dikhega hi nahi.
# Sirf wahi options aayenge jinka address aapne daala hai.
PAY_ADDRESSES = {
    "usdt_trc20": ("USDT (TRC20)", cfg("ADDR_USDT_TRC20", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
    "usdt_bep20": ("USDT (BEP20)", cfg("ADDR_USDT_BEP20", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
    "btc":        ("BTC",          cfg("ADDR_BTC", "")),
    "eth":        ("ETH",          cfg("ADDR_ETH", "")),
    "ltc":        ("LTC",          cfg("ADDR_LTC", "")),
    "trx":        ("TRX",          cfg("ADDR_TRX", "")),
}
# Buttons: (label, code) sirf un options ke jinka address set hai
PAY_OPTIONS = [(label, code) for code, (label, addr) in PAY_ADDRESSES.items() if addr]
PAY_LABELS = {code: label for label, code in PAY_OPTIONS}

# Form ke ye fields bharna zaroori hai (T/C optional hai)
REQUIRED_FIELDS = [
    "SELLER", "BUYER", "DEAL DETAIL", "DEAL AMOUNT", "EXPECTED TIME TO COMPLETE DEAL",
]
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


# ======================= ADMIN GROUP HELPERS =======================
def admin_id(context):
    return context.bot_data.get("admin_chat") or ADMIN_GROUP_ID


async def admin_call(context, method: str, *args, **kw):
    """Admin group par bot method chalata hai (group migrate hua ho to naye id par dobara)."""
    aid = admin_id(context)
    if aid is None:
        raise RuntimeError("ADMIN_GROUP_ID set nahi hai")
    try:
        return await getattr(context.bot, method)(aid, *args, **kw)
    except ChatMigrated as err:
        context.bot_data["admin_chat"] = err.new_chat_id
        return await getattr(context.bot, method)(err.new_chat_id, *args, **kw)


async def notify_admin(context, text: str):
    """Diagnostic message admin group ko (na ho paye to LOG_CHAT_ID ko)."""
    try:
        await admin_call(context, "send_message", text[:3900])
        return
    except Exception:
        pass
    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(LOG_CHAT_ID, text[:3900])
        except Exception:
            logging.exception("notify failed")


# ======================= USERBOT (group creator) =======================
# Telegram bots khud group nahi bana sakte, isliye ek dedicated user account use hota hai.
client = None  # post_init mein banega
USERBOT_ID = None  # userbot account ki id (ginti mein nahi aata)


def deal_title(label: str, deal_id: str) -> str:
    """'P2P Deal #ID' / 'Product Deal #ID'"""
    name = label if label.endswith("Deal") else f"{label} Deal"
    return f"{name} #{deal_id}"


async def leave_group(chat_id: int):
    """Userbot group chhodta hai. Returns (ok, error_text).
    Basic group ka creator chhod sakta hai; supergroup ka creator nahi (Telegram rule)."""
    try:
        if chat_id <= -1000000000000:  # supergroup / channel
            for attempt in (1, 2):
                try:
                    await client(LeaveChannelRequest(await client.get_input_entity(chat_id)))
                    break
                except ValueError:
                    if attempt == 2:
                        raise
                    await client.get_dialogs(limit=100)  # entity cache refresh
        else:  # basic group
            await client(DeleteChatUserRequest(chat_id=-chat_id, user_id=InputUserSelf()))
        logging.info("userbot left %s", chat_id)
        return True, ""
    except Exception as err:
        logging.exception("userbot leave failed")
        return False, f"{type(err).__name__}: {err}"[:300]


async def try_leave(context, chat_id: int, st: dict):
    if not USERBOT_LEAVE or client is None or st["userbot_left"] or st["leave_tries"] >= 3:
        return
    st["leave_tries"] += 1
    ok, err = await leave_group(chat_id)
    if ok:
        st["userbot_left"] = True
    elif st["leave_tries"] >= 3:
        await notify_admin(context, f"⚠️ Owner account could not leave {st['title'] or chat_id}.\n{err}")


async def maybe_leave(context, chat):
    """Member count 4+ (userbot + bot + buyer + seller) ho to userbot ko nikalne ki koshish."""
    st = deal_state(context, chat.id)
    if not USERBOT_LEAVE or st["userbot_left"] or st["leave_tries"] >= 3:
        return
    try:
        count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        return
    if count >= 4:
        await try_leave(context, chat.id, st)


async def watch_and_leave(context, chat_id: int):
    """Buyer + seller aane tak (10s gap, 30 min) dekhta hai, phir owner account ko nikalta hai."""
    for _ in range(180):
        await asyncio.sleep(10)
        st = deal_state(context, chat_id)
        if st["userbot_left"] or st["leave_tries"] >= 3:
            return
        try:
            count = await context.bot.get_chat_member_count(chat_id)
        except Exception:
            continue
        if count >= 4:  # owner + bot + buyer + seller
            await try_leave(context, chat_id, st)


async def _create_basic(bot_username: str, title: str):
    """Basic group: creator baad mein nikal sakta hai, to owner account group mein nahi dikhta."""
    res = await client(CreateChatRequest(users=[bot_username], title=title))
    updates = getattr(res, "updates", res)
    chat = updates.chats[0]
    bot_entity = await client.get_entity(bot_username)
    await client.edit_admin(chat, bot_entity, is_admin=True)
    invite = await client(ExportChatInviteRequest(chat, usage_limit=INVITE_LIMIT))
    return utils.get_peer_id(chat), invite.link


async def _create_super(bot_username: str, title: str):
    result = await client(CreateChannelRequest(
        title=title, about="Don Escrow Service - private deal group", megagroup=True,
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
    return utils.get_peer_id(channel), invite.link


async def create_deal_group(bot_username: str, label: str):
    """Naya private group banata hai. Returns (bot_chat_id, invite_link, deal_id, note).
    note = basic group fail hone ki wajah (agar supergroup fallback hua)."""
    deal_id = uuid.uuid4().hex[:6].upper()
    title = deal_title(label, deal_id)
    note = ""
    if GROUP_MODE == "basic":
        try:
            chat_id, link = await _create_basic(bot_username, title)
            return chat_id, link, deal_id, ""
        except Exception as err:
            logging.exception("basic group fail hua, supergroup try kar raha hoon")
            note = f"{type(err).__name__}: {err}"[:300]
    chat_id, link = await _create_super(bot_username, title)
    return chat_id, link, deal_id, note


# ======================= TEXTS =======================
def start_text() -> str:
    return (
        f"{e('party')} <b>Welcome to Don Escrow Service</b> {e('party')}\n\n"
        f"{e('shield')} Escrow : @xDonEscrow {e('check')}\n"
        f"{e('info')} Detail : @ZENOx0G {e('check')}\n"
        f"{e('support')} Customer help : @XdonZ {e('check')}"
    )


def select_text() -> str:
    return f"{e('shield')} <b>Please select your escrow type from below.</b>"


def deal_form_text() -> str:
    return (
        "ESCROW DEAL\n\n"
        "• SELLER : \n\n"
        "• BUYER : \n\n"
        "• DEAL DETAIL : \n\n"
        "• DEAL AMOUNT : \n\n"
        "• EXPECTED TIME TO COMPLETE DEAL : \n\n"
        "• T/C (IF ANY) : \n\n"
        "• ESCROW MORE THAN ESCROWER LIMIT AT YOUR OWN RISK"
    )


# ======================= KEYBOARDS =======================
def btn(label, icon, icons, url=None, cb=None) -> InlineKeyboardButton:
    kw = {"api_kwargs": {"icon_custom_emoji_id": eid(icon)}} if icons else {}
    return InlineKeyboardButton(label, url=url, callback_data=cb, **kw)


def start_kb(icons: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("Escrow", "shield", icons, cb="escrow")],
        [btn("Detail", "info", icons, url="https://t.me/ZENOx0G")],
        [btn("Customer help", "support", icons, url="https://t.me/XdonZ")],
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
        chat_id, link, deal_id, note = await create_deal_group(bot_username, label)
    except Exception as err:
        logging.exception("group creation failed")
        context.user_data["last_deal"] = 0
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(
                    LOG_CHAT_ID, f"Group creation error: {type(err).__name__}: {err}"[:3500])
            except Exception:
                pass
        if isinstance(err, errors.FloodWaitError):
            mins = max(1, err.seconds // 60)
            reason = f"Too many requests. Please try again after about {mins} minute(s)."
        else:
            reason = "Group could not be created. Please try again or contact @XdonZ."
        debug = html.escape(f"{type(err).__name__}: {err}"[:200])
        await status.edit_text(
            f"{e('cross')} {reason}\n\n<code>[{VERSION}] {debug}</code>", parse_mode=HTML)
        return

    await render(lambda icons: status.edit_text(
        f"{e('check')} <b>{label} group is ready!</b>\n\n"
        f"Join using the button below and add the other party.",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([[btn("Join Group", "link", icons, url=link)]]),
    ))

    mention = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'
    try:
        welcome = await context.bot.send_message(
            chat_id,
            f"{e('shield')} <b>{deal_title(label, deal_id)}</b>\n\n"
            f"{e('user')} Created by: {mention}\n"
            f"{e('info')} Please add the Buyer and Seller in this group.\n\n"
            f"{e('arrow')} Type /ready to get the deal form.",
            parse_mode=HTML,
        )
        # userbot ke "added ..." service messages hata do (group mein sirf bot + buyer + seller dikhein)
        if chat_id <= -1000000000000:  # supergroup mein message ids 1,2,3.. chat ke apne hote hain
            for mid in range(2, welcome.message_id):
                try:
                    await context.bot.delete_message(chat_id, mid)
                except Exception:
                    pass
    except Exception:
        logging.exception("group welcome message failed")

    st = deal_state(context, chat_id)
    st["title"] = deal_title(label, deal_id)
    if note:
        await notify_admin(context, (
            f"⚠️ {st['title']}: basic group could not be created, a supergroup was created instead "
            f"(owner account will stay visible).\nReason: {note}"))
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status not in ("administrator", "creator"):
            await notify_admin(context, (
                f"⚠️ Bot is not admin in {st['title']}, so it may not see all messages. "
                f"Make it admin or disable privacy mode in BotFather (/setprivacy)."))
    except Exception:
        logging.exception("bot admin check failed")
    if USERBOT_LEAVE:
        context.application.create_task(watch_and_leave(context, chat_id))

    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(
                LOG_CHAT_ID,
                f"New {deal_title(label, deal_id)} by {mention} (id {user.id})\n{link}",
                parse_mode=HTML, disable_web_page_preview=True,
            )
        except Exception:
            logging.exception("log message failed")


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin group mein Payment Received / Not Received button."""
    q = update.callback_query
    aid = admin_id(context)
    if aid is None or q.message.chat.id != aid:
        await q.answer("Not allowed.", show_alert=True)
        return

    _, action, cid = q.data.split(":")
    cid = int(cid)
    cid = context.bot_data.get("migrated", {}).get(cid, cid)
    st = deal_state(context, cid)
    if st["paid"]:
        await q.answer("Already confirmed.", show_alert=True)
        return

    admin = q.from_user
    who = f'<a href="tg://user?id={admin.id}">{html.escape(admin.first_name or "Admin")}</a>'
    title = html.escape(st["title"] or str(cid))
    st["admin_msg_id"] = None

    if action == "ok":
        st["paid"] = True
        await q.answer("Confirmed.")
        await q.message.edit_text(
            f"{e('check')} <b>Payment received - confirmed</b>\n\nDeal: {title}\nConfirmed by: {who}",
            parse_mode=HTML,
        )
        await render(lambda icons: context.bot.send_message(
            cid, f"{e('check')} <b>Payment received</b>", parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup(
                [[btn("Release Payment", "bolt", icons, cb=f"rel:{cid}")]]),
        ))
    else:
        await q.answer("Marked as not received.")
        await q.message.edit_text(
            f"{e('cross')} <b>Payment not received</b>\n\nDeal: {title}\nMarked by: {who}",
            parse_mode=HTML,
        )
        await context.bot.send_message(
            cid,
            f"{e('cross')} Payment not received yet. Please check and share the correct "
            f"payment screenshot.",
            parse_mode=HTML,
        )


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    "
