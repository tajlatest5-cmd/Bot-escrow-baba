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
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, PicklePersistence, filters,
)
from telethon import TelegramClient, utils, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CreateChannelRequest, InviteToChannelRequest, LeaveChannelRequest,
)
from telethon.tl.functions.messages import ExportChatInviteRequest

logging.basicConfig(level=logging.INFO)

# ======================= CONFIG =======================
def cfg(name: str, default: str = "") -> str:
    """Pehle hosting Variable dekhta hai, nahi mila to neeche likhi value."""
    return (os.getenv(name) or default).strip()


# Yahan quotes ke andar values paste kar sakte ho:
BOT_TOKEN = cfg("BOT_TOKEN", "8684366725:AAHm6v9iMNLSjSGCynhwSnhOzheM2aX9jD0")          # BotFather se token
API_ID = cfg("API_ID", "34145046")                # my.telegram.org se (sirf number)
API_HASH = cfg("API_HASH", "9eef1f689e6bde55fa0240660f7222ca")            # my.telegram.org se
USERBOT_SESSION = cfg("USERBOT_SESSION", "1AZWarzQBuynh2jMmOumHufr10ekAqgnZ7hkNjzdxxIhbsNAl5y5u0HDd9p0_XcUJi295fuKnmXE7jZqV2rmwikZaDlsLOINBIBxegsDGpsZZ8QLc5Q0FWeC8W32VibhyAkqsMLarxxdCHkYJDkqppUPq-y0jNWAxOBHBGTdkqE9WhPjAq7ZCbyB5k9F4GHsxPDIyuo0TWZ9pxtw8vTqrM3CAlzphHligzz2iAL76KCRml_h4-ygcWCEsOI93ukfZ5BVtLmlEHKf8pvqB8GLuClCNuCQJpP3e47yLXd52c-ZwhKDqhN0F6kkR09zJ_s9zkTz9JFzZVe1y8Wp2_9w4DdKagZRDAuA=")  # python bot.py session se mili string
LOG_CHAT_ID = cfg("LOG_CHAT_ID", "")      # optional: naye deal ki info is chat mein
_admin_raw = cfg("ADMIN_GROUP_ID", "-5514040923")    # admin group ki ID (group mein /id likho to milegi)
ADMIN_GROUP_ID = int(_admin_raw) if re.fullmatch(r"-?\d+", _admin_raw) else None
INVITE_LIMIT = int(cfg("INVITE_LIMIT", "2"))  # ek link par max log (buyer + seller)
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
    "btc":        ("BTC",          cfg("ADDR_BTC", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
    "eth":        ("ETH",          cfg("ADDR_ETH", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
    "ltc":        ("LTC",          cfg("ADDR_LTC", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
    "trx":        ("TRX",          cfg("ADDR_TRX", "TJhJBir2MggnBbheDdyxWcMNvGDnihCvZA")),
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


# ======================= USERBOT (group creator) =======================
# Telegram bots khud group nahi bana sakte, isliye ek dedicated user account use hota hai.
client = None  # post_init mein banega
USERBOT_ID = None  # userbot account ki id (ginti mein nahi aata)


def deal_title(label: str, deal_id: str) -> str:
    """'P2P Deal #ID' / 'Product Deal #ID'"""
    name = label if label.endswith("Deal") else f"{label} Deal"
    return f"{name} #{deal_id}"


async def leave_group(chat_id: int):
    """Userbot group chhod deta hai taaki group mein sirf bot + buyer + seller rahein."""
    try:
        await client(LeaveChannelRequest(await client.get_input_entity(chat_id)))
        logging.info("userbot left %s", chat_id)
    except Exception:
        logging.exception("userbot leave failed")


async def create_deal_group(bot_username: str, label: str):
    """Naya private group banata hai. Returns (bot_chat_id, invite_link, deal_id)."""
    deal_id = uuid.uuid4().hex[:6].upper()
    result = await client(CreateChannelRequest(
        title=deal_title(label, deal_id),
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
        chat_id, link, deal_id = await create_deal_group(bot_username, label)
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
            f"{e('cross')} {reason}\n\n<code>[v14] {debug}</code>", parse_mode=HTML)
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
        for mid in range(2, welcome.message_id):
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass
    except Exception:
        logging.exception("group welcome message failed")

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
    if ADMIN_GROUP_ID is None or q.message.chat.id != ADMIN_GROUP_ID:
        await q.answer("Not allowed.", show_alert=True)
        return

    _, action, cid = q.data.split(":")
    cid = int(cid)
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
    """/id - is chat ki ID batata hai (ADMIN_GROUP_ID ke liye)."""
    await update.message.reply_text(
        f"Chat ID: <code>{update.effective_chat.id}</code>", parse_mode=HTML)


async def register_join(chat, users, context: ContextTypes.DEFAULT_TYPE):
    """Buyer aur seller join hone par userbot group chhod deta hai."""
    if not chat or "Deal #" not in (chat.title or ""):
        return

    st = deal_state(context, chat.id)
    for m in users:
        if m.is_bot or m.id == USERBOT_ID:
            continue
        st["humans"].add(m.id)

    logging.info("deal %s humans=%s", chat.id, st["humans"])
    if USERBOT_LEAVE and len(st["humans"]) >= 2 and not st["userbot_left"]:
        st["userbot_left"] = True
        await leave_group(chat.id)


def deal_state(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict:
    deals = context.bot_data.setdefault("deals", {})
    st = deals.setdefault(chat_id, {})
    defaults = {
        "humans": set(), "userbot_left": False, "form_msg_id": None,
        "pay_asked": False, "crypto": None, "form_text": "", "title": "",
        "paid": False, "admin_msg_id": None, "payer_id": None,
        "release_asked": False, "awaiting_addr": False, "seller_addr": "",
        "released": False,
    }
    for k, v in defaults.items():
        st.setdefault(k, v)
    return st


def is_deal_chat(chat) -> bool:
    return bool(chat and "Deal #" in (chat.title or ""))


def parse_form(text: str) -> dict:
    """Message se form ke fields nikalta hai. Returns {FIELD: value}."""
    out = {}
    for key in REQUIRED_FIELDS:
        m = re.search(rf"^[^\w\n]*{re.escape(key)}[ \t]*:[ \t]*(.*)$", text, re.I | re.M)
        out[key] = (m.group(1).strip() if m else None)
    return out


async def ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ready likhne par ESCROW DEAL form aata hai."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    st = deal_state(context, chat.id)
    if st["form_msg_id"]:
        await update.message.reply_text(
            "The deal form is already sent above. Please fill it and send it here.",
            reply_to_message_id=st["form_msg_id"],
        )
        return
    form = await context.bot.send_message(chat.id, deal_form_text())
    st["form_msg_id"] = form.message_id
    await context.bot.send_message(
        chat.id,
        "Buyer or Seller, please copy the form above, fill it and send it here.",
        reply_to_message_id=form.message_id,
    )


async def handle_form(msg, chat, st, context):
    """Bhara hua form aate hi crypto payment ka sawal poochta hai."""
    fields = parse_form(msg.text)
    missing = [k for k, v in fields.items() if not v]
    if missing:
        await msg.reply_text(
            "Please fill all the details in the form. Missing: " + ", ".join(missing),
            reply_to_message_id=msg.message_id,
        )
        return

    st["pay_asked"] = True
    st["form_text"] = msg.text
    st["title"] = chat.title or ""
    if not PAY_OPTIONS:
        logging.warning("Koi payment address set nahi hai (ADDR_... variables).")
        await msg.reply_text("Payment details will be shared here shortly.",
                             reply_to_message_id=msg.message_id)
        return
    rows = []
    for i in range(0, len(PAY_OPTIONS), 2):
        rows.append([("pay:" + c, l) for l, c in PAY_OPTIONS[i:i + 2]])

    def kb(icons):
        return InlineKeyboardMarkup([[btn(l, "bolt", icons, cb=cb) for cb, l in row] for row in rows])

    await render(lambda icons: context.bot.send_message(
        chat.id,
        f"{e('briefcase')} <b>Which crypto would you like to pay in?</b>",
        parse_mode=HTML, reply_markup=kb(icons), reply_to_message_id=msg.message_id,
    ))


def is_image(msg) -> bool:
    return bool(msg.photo or (msg.document and (msg.document.mime_type or "").startswith("image/")))


async def handle_proof(msg, chat, st, context):
    """Payer ka payment screenshot admin group mein bhejta hai."""
    if not is_image(msg):
        return  # sirf screenshot
    if st["payer_id"] and msg.from_user and msg.from_user.id != st["payer_id"]:
        return  # sirf payer ka screenshot
    if ADMIN_GROUP_ID is None:
        logging.warning("ADMIN_GROUP_ID set nahi hai, screenshot forward nahi hua.")
        return

    try:
        await context.bot.forward_message(ADMIN_GROUP_ID, chat.id, msg.message_id)
    except Exception:
        try:
            await context.bot.copy_message(ADMIN_GROUP_ID, chat.id, msg.message_id)
        except Exception:
            logging.exception("proof forward failed")
            return

    # purana control message hata ke naya bhejo, taaki buttons hamesha sabse neeche rahein
    if st["admin_msg_id"]:
        try:
            await context.bot.delete_message(ADMIN_GROUP_ID, st["admin_msg_id"])
        except Exception:
            pass

    title = html.escape(st["title"] or chat.title or "")
    summary = html.escape(st["form_text"])[:2500]
    control = None

    async def send(icons):
        nonlocal control
        control = await context.bot.send_message(
            ADMIN_GROUP_ID,
            f"{e('briefcase')} <b>Payment screenshot received</b>\n\n"
            f"Deal: {title}\nCrypto: {html.escape(st['crypto'] or '-')}\n\n"
            f"{summary}\n\n"
            f"Please check the payment and confirm.",
            parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup([[
                btn("Payment Received", "check", icons, cb=f"adm:ok:{chat.id}"),
                btn("Not Received", "cross", icons, cb=f"adm:no:{chat.id}"),
            ]]),
        )
        return control

    await render(send)
    if control:
        st["admin_msg_id"] = control.message_id


ADDR_RE = re.compile(r"\b(?:0x[a-fA-F0-9]{40}|[A-Za-z0-9]{26,90})\b")


async def handle_seller_address(msg, chat, st, addr, context):
    """Seller ka address admin group ko bhejta hai (payment release ke liye)."""
    st["seller_addr"] = addr
    st["awaiting_addr"] = False
    await msg.reply_text("Address received. The admin will release the payment shortly.",
                         reply_to_message_id=msg.message_id)
    if ADMIN_GROUP_ID is None:
        logging.warning("ADMIN_GROUP_ID set nahi hai, seller address admin ko nahi gaya.")
        return

    fields = parse_form(st["form_text"]) if st["form_text"] else {}
    sent = await context.bot.send_message(
        ADMIN_GROUP_ID,
        f"{e('briefcase')} <b>Payment release request</b>\n\n"
        f"Deal: {html.escape(st['title'] or chat.title or '')}\n"
        f"Crypto: {html.escape(st['crypto'] or '-')}\n"
        f"Amount: {html.escape(fields.get('DEAL AMOUNT') or '-')}\n\n"
        f"SELLER ADDRESS : <code>{html.escape(addr)}</code>\n\n"
        f"Please release the payment, then <b>reply to this message</b> with the payment screenshot.",
        parse_mode=HTML,
    )
    context.bot_data.setdefault("release_map", {})[sent.message_id] = chat.id


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not is_deal_chat(chat):
        return
    st = deal_state(context, chat.id)

    # 1) bhara hua form
    if msg.text and not st["pay_asked"]:
        up = msg.text.upper()
        if "DEAL AMOUNT" in up and "SELLER" in up and "BUYER" in up:
            await handle_form(msg, chat, st, context)
            return

    # 2) payer ka screenshot (crypto select hone ke baad, admin confirm hone tak)
    if st["crypto"] and not st["paid"]:
        await handle_proof(msg, chat, st, context)
        return

    # 3) release: seller apna address bheje
    if st["paid"] and st["awaiting_addr"] and msg.text:
        if st["payer_id"] and msg.from_user and msg.from_user.id == st["payer_id"]:
            return  # buyer ka message address nahi hota
        m = ADDR_RE.search(msg.text)
        if m:
            await handle_seller_address(msg, chat, st, m.group(0), context)


async def start_release(context, chat_id: int, user_id: int):
    """Buyer ke release request ko check karta hai. Returns (ok, error_text)."""
    st = deal_state(context, chat_id)
    if not st["paid"]:
        return False, "Payment is not confirmed yet."
    if st["payer_id"] and user_id != st["payer_id"]:
        return False, "Only the buyer can release the payment."
    if st["released"]:
        return False, "Payment is already released."
    if st["release_asked"]:
        return False, "Release request is already sent."
    st["release_asked"] = True
    st["awaiting_addr"] = True
    return True, ""


async def announce_release(context, chat_id: int):
    st = deal_state(context, chat_id)
    await context.bot.send_message(
        chat_id,
        f"{e('check')} <b>Release request received.</b>\n\n"
        f"Seller, please send your {html.escape(st['crypto'] or '')} address here to receive the payment.",
        parse_mode=HTML,
    )


async def release_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/release - buyer payment release karne ko kehta hai."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    ok, err = await start_release(context, chat.id, update.effective_user.id)
    if ok:
        await announce_release(context, chat.id)
    else:
        await update.message.reply_text(err)


async def release_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Release Payment' button."""
    q = update.callback_query
    chat = q.message.chat
    if not is_deal_chat(chat):
        await q.answer()
        return
    ok, err = await start_release(context, chat.id, q.from_user.id)
    if not ok:
        await q.answer(err, show_alert=True)
        return
    await q.answer()
    await announce_release(context, chat.id)


async def admin_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin release ka screenshot release-request message ko reply karke bhejta hai -> deal group mein jata hai."""
    msg = update.message
    ref = msg.reply_to_message
    if not ref:
        return
    deal_chat = context.bot_data.get("release_map", {}).get(ref.message_id)
    if not deal_chat:
        return
    st = deal_state(context, deal_chat)
    if st["released"]:
        await msg.reply_text("Already released.")
        return
    await context.bot.copy_message(
        deal_chat, msg.chat_id, msg.message_id,
        caption=f"{e('check')} <b>Payment released</b>", parse_mode=HTML,
    )
    st["released"] = True
    await msg.reply_text("Screenshot sent to the deal group.")


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat = q.message.chat
    if not is_deal_chat(chat):
        await q.answer()
        return
    st = deal_state(context, chat.id)
    if st["crypto"]:
        await q.answer(f"Already selected: {st['crypto']}", show_alert=True)
        return

    label = PAY_LABELS.get(q.data.split(":")[1])
    if not label:
        await q.answer()
        return
    st["crypto"] = label
    st["payer_id"] = q.from_user.id  # jisne crypto chuna wahi payer (buyer)
    st["title"] = chat.title or st["title"]
    await q.answer()

    user = q.from_user
    mention = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'
    await q.message.edit_text(
        f"{e('check')} <b>Crypto selected:</b> {label}\n"
        f"{e('user')} Selected by: {mention}",
        parse_mode=HTML,
    )
    address = PAY_ADDRESSES[q.data.split(":")[1]][1]
    await context.bot.send_message(
        chat.id,
        f"ADDRESS : <code>{html.escape(address)}</code>\n\n"
        "Please share your payment screenshot after making the payment.",
        parse_mode=HTML,
    )

    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(
                LOG_CHAT_ID,
                f"Deal ready for payment\nGroup: {chat.title} ({chat.id})\n"
                f"Crypto: {label}\n\n{st['form_text']}"[:3900],
            )
        except Exception:
            logging.exception("log message failed")


async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Service message 'joined the group' se (agar Telegram bhejta hai)."""
    m = update.message
    if USERBOT_ID and m.from_user and m.from_user.id == USERBOT_ID:
        try:
            await m.delete()  # userbot ne jo add kiya uska "added ..." message hata do
        except Exception:
            pass
    await register_join(update.effective_chat, update.message.new_chat_members, context)


async def on_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Userbot group chhode to uska 'left the group' message hata do."""
    m = update.message
    if USERBOT_ID and m.left_chat_member and m.left_chat_member.id == USERBOT_ID:
        try:
            await m.delete()
        except Exception:
            pass


async def on_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """chat_member update se: invite link se join karne par bhi pakad leta hai."""
    cm = update.chat_member
    if not cm:
        return
    joined = (
        cm.old_chat_member.status in ("left", "kicked")
        and cm.new_chat_member.status in ("member", "administrator", "creator", "restricted")
    )
    if joined:
        await register_join(update.effective_chat, [cm.new_chat_member.user], context)


async def post_init(app: Application):
    global client
    client = TelegramClient(StringSession(USERBOT_SESSION), int(API_ID), API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("USERBOT_SESSION invalid hai. gen_session.py dobara chalao.")
    global USERBOT_ID
    USERBOT_ID = (await client.get_me()).id
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
    logging.info("=== Don Escrow bot v14 starting ===")

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

    app = (
        Application.builder().token(BOT_TOKEN)
        .persistence(PicklePersistence(filepath="bot_data.pkl"))
        .post_init(post_init).post_shutdown(post_shutdown).build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(escrow, pattern=r"^escrow$"))
    app.add_handler(CallbackQueryHandler(deal, pattern=r"^deal:(p2p|product)$"))
    app.add_handler(CommandHandler("ready", ready, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(pay, pattern=r"^pay:[a-z0-9_]+$"))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^adm:(ok|no):-?\d+$"))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
        on_group_message))
    app.add_handler(CommandHandler("release", release_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(release_cb, pattern=r"^rel:-?\d+$"))
    if ADMIN_GROUP_ID is not None:
        app.add_handler(MessageHandler(
            filters.Chat(chat_id=ADMIN_GROUP_ID) & filters.REPLY
            & (filters.PHOTO | filters.Document.IMAGE),
            admin_screenshot), group=1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
