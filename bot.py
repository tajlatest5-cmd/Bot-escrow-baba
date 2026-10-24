"""
Don Escrow Service bot - single file.

Sirf 2 files: bot.py + requirements.txt

1) Neeche CONFIG mein values paste karo (ya hosting ke Variables mein daalo).
2) Session string nikalne ke liye (ek baar, apne computer par):  python bot.py session
3) Bot chalane ke liye:  python bot.py
"""
import os
import re
import random
import sys
import asyncio
import time
import html
import uuid
import logging

from types import SimpleNamespace

from telegram import BotCommand, BotCommandScopeAllGroupChats, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, ChatMigrated, Forbidden
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, PicklePersistence, filters,
)
from telethon import TelegramClient, utils, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CreateChannelRequest, DeleteChannelRequest, InviteToChannelRequest, LeaveChannelRequest,
)
from telethon.tl.functions.messages import (
    CreateChatRequest, DeleteChatRequest, DeleteChatUserRequest, ExportChatInviteRequest,
)
from telethon.tl.types import InputUserSelf

logging.basicConfig(level=logging.INFO)
VERSION = "v25"

# ======================= CONFIG =======================
def cfg(name: str, default: str = "") -> str:
    """Pehle hosting Variable dekhta hai, nahi mila to neeche likhi value."""
    return (os.getenv(name) or default).strip()


# Yahan quotes ke andar values paste kar sakte ho:
BOT_TOKEN = cfg("BOT_TOKEN", "")          # BotFather se token
API_ID = cfg("API_ID", "")                # my.telegram.org se (sirf number)
API_HASH = cfg("API_HASH", "")            # my.telegram.org se
# 3-4 userbot accounts ki session strings (python bot.py session se). Har ek ko alag Variable do:
# USERBOT_SESSION, USERBOT_SESSION_2, USERBOT_SESSION_3, USERBOT_SESSION_4 ...
# (ya ek hi Variable USERBOT_SESSIONS mein comma se alag-alag). Quotes ke andar yahan bhi paste kar sakte ho.
SESSION_LIST = [
    cfg("USERBOT_SESSION", ""), cfg("USERBOT_SESSION_2", ""), cfg("USERBOT_SESSION_3", ""),
    cfg("USERBOT_SESSION_4", ""), cfg("USERBOT_SESSION_5", ""), cfg("USERBOT_SESSION_6", ""),
]
SESSION_LIST += [x.strip() for x in cfg("USERBOT_SESSIONS", "").replace("\n", ",").split(",")]
SESSION_LIST = list(dict.fromkeys(x for x in SESSION_LIST if x))  # khaali hatao, duplicate hatao
LOG_CHAT_ID = cfg("LOG_CHAT_ID", "").strip('"\' ')  # optional: errors/alerts is chat mein (apna user ID)
_admin_raw = cfg("ADMIN_GROUP_ID", "")    # admin group ki ID (group mein /id likho to milegi)
_admin_digits = re.sub(r"[^\d-]", "", _admin_raw)  # quotes / space / extra akshar hata do
ADMIN_GROUP_ID = int(_admin_digits) if re.fullmatch(r"-?\d+", _admin_digits) else None
INVITE_LIMIT = int(cfg("INVITE_LIMIT", "2"))  # ek link par max log (buyer + seller)
GROUP_MODE = cfg("GROUP_MODE", "basic")  # basic = owner (userbot) baad mein nikal sakta hai; super = supergroup
USERBOT_LEAVE = cfg("USERBOT_LEAVE", "1") == "1"  # buyer+seller aane ke baad userbot group chhod de
COOLDOWN = 60  # seconds, ek user ke do group ke beech
MAX_GROUPS_PER_HOUR = int(cfg("MAX_GROUPS_PER_HOUR", "20"))  # sabhi accounts mila ke
MIN_GROUP_GAP = int(cfg("MIN_GROUP_GAP", "30"))  # do group ke beech kam se kam seconds (sabhi mila ke)
# Har account par alag limit (freeze se bachne ke liye). Bot kaam ko accounts mein baant deta hai.
ACCT_MAX_PER_HOUR = int(cfg("ACCT_MAX_PER_HOUR", "3"))
ACCT_MAX_PER_DAY = int(cfg("ACCT_MAX_PER_DAY", "12"))
ACCT_MIN_GAP = int(cfg("ACCT_MIN_GAP", "120"))  # ek hi account se do group ke beech seconds
MAX_GROUPS_PER_USER_DAY = int(cfg("MAX_GROUPS_PER_USER_DAY", "5"))  # ek user ke din mein max groups
IDLE_SECONDS = int(cfg("IDLE_SECONDS", "600"))  # itni der koi message na aaye to group delete (10 min)
COMPLETE_DELETE_SECONDS = int(cfg("COMPLETE_DELETE_SECONDS", "120"))  # deal complete ke itne baad delete
SHOW_DEBUG = cfg("SHOW_DEBUG", "0") == "1"  # 1 = user ko error ka naam dikhao
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
    "usdt_trc20": ("USDT (TRC20)", cfg("ADDR_USDT_TRC20", "")),
    "usdt_bep20": ("USDT (BEP20)", cfg("ADDR_USDT_BEP20", "")),
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


# ======================= BACKGROUND TASKS / ACTIVITY =======================
BG_TASKS = set()


def spawn(coro):
    """Background task (shutdown ko block nahi karta)."""
    t = asyncio.get_running_loop().create_task(coro)
    BG_TASKS.add(t)
    t.add_done_callback(BG_TASKS.discard)
    return t


def touch(st: dict):
    """Group mein activity hui: delete timer dobara 10 min se shuru."""
    if st["closed"] or st["completed"] or st.get("hold"):
        return
    now = time.time()
    st["last_activity"] = now
    st["delete_at"] = now + IDLE_SECONDS
    st["warned"] = False


# ======================= ADMIN GROUP HELPERS =======================
def admin_id(context):
    return context.bot_data.get("admin_chat") or ADMIN_GROUP_ID


def admin_candidates(aid: int) -> list:
    """Agar ID mein '-' bhool gaye ho to dono tareeke try karo."""
    if aid > 0:
        return [-aid, int(f"-100{aid}")]
    return [aid]


async def admin_call(context, method: str, *args, **kw):
    """Admin group par bot method chalata hai (group migrate hua ho ya ID galat likhi ho to bhi koshish)."""
    aid = admin_id(context)
    if aid is None:
        raise RuntimeError("ADMIN_GROUP_ID set nahi hai")
    last = None
    for cand in admin_candidates(aid):
        try:
            res = await getattr(context.bot, method)(cand, *args, **kw)
            if cand != aid:
                context.bot_data["admin_chat"] = cand
            return res
        except ChatMigrated as err:
            context.bot_data["admin_chat"] = err.new_chat_id
            return await getattr(context.bot, method)(err.new_chat_id, *args, **kw)
        except (BadRequest, Forbidden) as err:
            last = err
    raise last


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
class Acct:
    """Ek userbot account."""
    def __init__(self, idx: int, session: str):
        self.idx = idx
        self.session = session
        self.client = None
        self.user_id = None
        self.ok = False
        self.err = ""
        self.fatal = False      # True = freeze/logout (khud theek nahi hoga)
        self.last_conn_alert = 0.0
        self.cool_until = 0.0   # is waqt tak is account ko kaam nahi dena (flood/limit)
        self.times = []         # group banane ke samay


class NoAccountAvailable(Exception):
    pass


ACCOUNTS = []
FATAL_WORDS = ("Frozen", "Deactivated", "Banned", "AuthKey", "SessionRevoked", "SessionExpired")


def userbot_ids() -> set:
    return {a.user_id for a in ACCOUNTS if a.user_id}


def is_userbot(uid) -> bool:
    return uid in userbot_ids()


def any_ok() -> bool:
    return any(a.ok for a in ACCOUNTS)


def acct_for(st: dict):
    """Is deal group ko jis account ne banaya uska Acct."""
    idx = st.get("acct")
    for a in ACCOUNTS:
        if a.idx == idx:
            return a
    return None


def pick_account(exclude=()):
    """Sabse kam use hua, theek-thaak account chunta hai (har account ki limit ke andar)."""
    now = time.time()
    best = None
    for a in ACCOUNTS:
        if not a.ok or a.idx in exclude or a.cool_until > now:
            continue
        a.times = [t for t in a.times if now - t < 86400]
        hour = [t for t in a.times if now - t < 3600]
        if len(hour) >= ACCT_MAX_PER_HOUR or len(a.times) >= ACCT_MAX_PER_DAY:
            continue
        if a.times and now - a.times[-1] < ACCT_MIN_GAP:
            continue
        key = (len(hour), a.times[-1] if a.times else 0)
        if best is None or key < best[0]:
            best = (key, a)
    return best[1] if best else None


def is_conn_error(err: Exception) -> bool:
    return isinstance(err, (ConnectionError, OSError, asyncio.TimeoutError)) or \
        "disconnected" in str(err).lower()


async def ensure_connected(acct) -> None:
    """Client disconnect ho gaya ho to wapas jod do."""
    cl = acct.client
    if cl is not None and not cl.is_connected():
        await cl.connect()


async def reconnect(acct, timeout: int = 60) -> None:
    """Pura reconnect (disconnect + connect) aur session check."""
    cl = acct.client
    try:
        await cl.disconnect()
    except Exception:
        pass
    await asyncio.wait_for(cl.connect(), timeout)
    if not await cl.is_user_authorized():
        acct.fatal = True
        raise RuntimeError("session invalid hai ya account logout/freeze hai")


async def run_with_reconnect(acct, fn):
    """fn() chalao; connection toot gaya ho to reconnect karke ek baar aur."""
    try:
        await ensure_connected(acct)
        return await fn()
    except Exception as err:
        if not is_conn_error(err):
            raise
        logging.warning("account #%s connection toota (%s), reconnect kar raha hoon", acct.idx, err)
        await reconnect(acct)
        return await fn()


def accounts_report() -> str:
    """Har account ki halat (wajah ke saath)."""
    lines = []
    for a in ACCOUNTS:
        if a.ok:
            lines.append(f"#{a.idx}: OK")
        else:
            lines.append(f"#{a.idx}: NOT working - {a.err[:150] or 'unknown reason'}")
    return "\n".join(lines) or "no accounts configured"


async def recheck_accounts() -> None:
    """Sabhi accounts ko abhi dobara jodke check karta hai (freeze/logout ho to wajah save karta hai)."""
    for a in ACCOUNTS:
        if a.client is None:
            continue
        a.fatal = False
        try:
            await reconnect(a, timeout=20)
            await asyncio.wait_for(a.client.get_me(), 20)
            a.ok = True
            a.err = ""
        except Exception as err:
            a.ok = False
            a.err = f"{type(err).__name__}: {err}"[:300]
            if any(w in type(err).__name__ for w in FATAL_WORDS):
                a.fatal = True


async def keepalive():
    """Har 45 second mein dekhta hai ki accounts jude hue hain; toote hon to jod deta hai."""
    while True:
        await asyncio.sleep(45)
        for a in ACCOUNTS:
            if a.client is None or a.fatal:
                continue
            try:
                if not a.client.is_connected():
                    await reconnect(a)
                    if not a.ok:
                        a.ok = True
                        a.err = ""
                        logging.info("Account #%s wapas connected.", a.idx)
            except Exception as err:
                if not a.fatal:
                    a.ok = False
                    a.err = f"{type(err).__name__}: {err}"[:300]
                logging.warning("Account #%s reconnect fail: %s", a.idx, a.err)


async def handle_acct_error(context, acct: "Acct", err: Exception):
    """Account ke error ke hisaab se use rok do aur admin ko batao."""
    name = type(err).__name__
    now = time.time()
    if is_conn_error(err):
        acct.cool_until = now + 60
        if now - acct.last_conn_alert < 600:  # alert baar-baar nahi
            return
        acct.last_conn_alert = now
        note = "lost its connection. The bot is reconnecting it automatically."
    elif any(w in name for w in FATAL_WORDS):
        acct.ok = False
        acct.fatal = True
        acct.err = f"{name}: {err}"[:300]
        note = "stopped working (frozen / logged out). Other accounts will be used."
    elif isinstance(err, errors.FloodWaitError):
        acct.cool_until = now + err.seconds + 60
        note = f"is resting for about {max(1, err.seconds // 60)} minute(s) (Telegram flood limit)."
    elif "PeerFlood" in name or "UserRestricted" in name:
        acct.cool_until = now + 6 * 3600
        note = "hit a Telegram limit, resting for 6 hours."
    else:
        acct.cool_until = now + 300
        note = "had an error, resting for 5 minutes."
    await notify_admin(context, f"⚠️ Account #{acct.idx} {note}\n{name}: {err}"[:3500])


def deal_title(label: str, deal_id: str) -> str:
    """'P2P Deal #ID' / 'Product Deal #ID'"""
    name = label if label.endswith("Deal") else f"{label} Deal"
    return f"{name} #{deal_id}"


async def leave_group(cl, chat_id: int):
    """Userbot group chhodta hai. Returns (ok, error_text).
    Basic group ka creator chhod sakta hai; supergroup ka creator nahi (Telegram rule)."""
    try:
        if chat_id <= -1000000000000:  # supergroup / channel
            for attempt in (1, 2):
                try:
                    await cl(LeaveChannelRequest(await cl.get_input_entity(chat_id)))
                    break
                except ValueError:
                    if attempt == 2:
                        raise
                    await cl.get_dialogs(limit=100)  # entity cache refresh
        else:  # basic group
            await cl(DeleteChatUserRequest(chat_id=-chat_id, user_id=InputUserSelf()))
        logging.info("userbot left %s", chat_id)
        return True, ""
    except Exception as err:
        logging.exception("userbot leave failed")
        return False, f"{type(err).__name__}: {err}"[:300]


async def try_leave(context, chat_id: int, st: dict):
    acct = acct_for(st)
    if not USERBOT_LEAVE or acct is None or acct.client is None or st["userbot_left"] or st["leave_tries"] >= 3:
        return
    st["leave_tries"] += 1
    try:
        await ensure_connected(acct)
    except Exception:
        logging.exception("leave se pehle connect nahi hua")
    try:  # nikalne se pehle member list yaad rakho (baad mein group saaf karne ke kaam aayegi)
        parts = await acct.client.get_participants(chat_id)
        st["members"] = {p.id for p in parts if not is_userbot(p.id) and not getattr(p, "bot", False)}
    except Exception:
        logging.exception("participants list nahi mili")
    ok, err = await leave_group(acct.client, chat_id)
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


async def delete_group_as_creator(cl, chat_id: int) -> bool:
    """Owner account group ko sabke liye delete karta hai (sirf creator kar sakta hai)."""
    try:
        if chat_id <= -1000000000000:
            await cl(DeleteChannelRequest(await cl.get_input_entity(chat_id)))
        else:
            await cl(DeleteChatRequest(chat_id=-chat_id))
        return True
    except Exception:
        logging.exception("creator delete failed")
        return False


async def close_group(app, chat_id: int, reason: str):
    """Group band: owner account ho to delete, nahi to sab members hata ke bot nikal jata hai."""
    ctx = SimpleNamespace(bot=app.bot, bot_data=app.bot_data)
    st = deal_state(ctx, chat_id)
    if st["closed"]:
        return
    st["closed"] = True
    title = st["title"] or str(chat_id)
    in_progress = bool(st["crypto"]) and not st["completed"]

    try:
        await app.bot.send_message(chat_id, "🗑 This group is being deleted now.")
        await asyncio.sleep(2)
    except Exception:
        pass

    how = "emptied"
    acct = acct_for(st)
    if acct is not None and acct.ok and acct.client is not None and not st["userbot_left"]:
        try:
            await ensure_connected(acct)
        except Exception:
            logging.exception("delete se pehle connect nahi hua")
        if await delete_group_as_creator(acct.client, chat_id):
            how = "deleted"
    if how != "deleted":
        for uid in set(st["humans"]) | set(st["members"]):
            if uid == getattr(app.bot, "id", None) or is_userbot(uid):
                continue
            try:
                await app.bot.ban_chat_member(chat_id, uid)
            except Exception:
                logging.warning("member %s hataya nahi ja saka", uid)
        try:
            await app.bot.leave_chat(chat_id)
        except Exception:
            logging.exception("bot leave failed")

    text = f"🗑 {title}: group {how} ({reason})."
    if in_progress:
        text = "⚠️ " + text + " The deal was still in progress, check this group's messages above."
    await notify_admin(ctx, text)


async def janitor(app):
    """Har 30 second mein dekhta hai: kaunsa group idle ya complete hai -> delete."""
    while True:
        await asyncio.sleep(30)
        try:
            now = time.time()
            for chat_id, st in list(app.bot_data.get("deals", {}).items()):
                if st.get("closed"):
                    if now - (st.get("delete_at") or 0) > 86400:
                        app.bot_data["deals"].pop(chat_id, None)  # purani state saaf
                    continue
                if not st.get("delete_at"):
                    continue
                left = st["delete_at"] - now
                if left <= 0:
                    await close_group(app, chat_id, "deal completed" if st["completed"] else "inactive")
                elif left <= 120 and not st["warned"] and not st["completed"]:
                    st["warned"] = True
                    try:
                        await app.bot.send_message(
                            chat_id, "⚠️ This group will be deleted in 2 minutes due to inactivity. "
                                     "Send any message to keep it.")
                    except Exception:
                        pass
        except Exception:
            logging.exception("janitor error")


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


async def ensure_bot_admin(context, acct, bot_username: str, chat_id: int):
    """Bot group mein admin hona chahiye (warna privacy mode mein wo plain messages/photos nahi dekhta).
    Admin na ho to owner account se dobara admin banane ki koshish. Returns (ok, last_error)."""
    last = ""
    try:
        await ensure_connected(acct)
    except Exception:
        logging.exception("admin banane se pehle connect nahi hua")
    for attempt in range(2):
        try:
            me = await context.bot.get_chat_member(chat_id, context.bot.id)
            if me.status in ("administrator", "creator"):
                return True, ""
            last = f"bot status: {me.status}"
        except Exception as err:
            last = f"{type(err).__name__}: {err}"[:200]
        try:
            cl = acct.client
            ent = await cl.get_input_entity(chat_id)
            bot_ent = await cl.get_entity(bot_username)
            if chat_id <= -1000000000000:
                await cl.edit_admin(ent, bot_ent, change_info=True, delete_messages=True,
                                    ban_users=True, invite_users=True, pin_messages=True)
            else:
                await cl.edit_admin(ent, bot_ent, is_admin=True)
        except Exception as err:
            last = f"{type(err).__name__}: {err}"[:200]
            logging.exception("bot ko admin banana fail")
        await asyncio.sleep(2)
    return False, last


async def _create_basic(cl, bot_username: str, title: str):
    """Basic group: creator baad mein nikal sakta hai, to owner account group mein nahi dikhta."""
    res = await cl(CreateChatRequest(users=[bot_username], title=title))
    updates = getattr(res, "updates", res)
    chat = updates.chats[0]
    await asyncio.sleep(random.uniform(1.5, 3.5))  # insaan jaisi gati (freeze se bachne ke liye)
    bot_entity = await cl.get_entity(bot_username)
    await cl.edit_admin(chat, bot_entity, is_admin=True)
    await asyncio.sleep(random.uniform(1.0, 2.5))
    invite = await cl(ExportChatInviteRequest(chat, usage_limit=INVITE_LIMIT))
    return utils.get_peer_id(chat), invite.link


async def _create_super(cl, bot_username: str, title: str):
    result = await cl(CreateChannelRequest(
        title=title, about="Don Escrow Service - private deal group", megagroup=True,
    ))
    channel = result.chats[0]
    await asyncio.sleep(random.uniform(1.5, 3.5))
    bot_entity = await cl.get_entity(bot_username)
    await cl(InviteToChannelRequest(channel, [bot_entity]))
    await asyncio.sleep(random.uniform(1.0, 2.5))
    await cl.edit_admin(
        channel, bot_entity,
        change_info=True, delete_messages=True, ban_users=True,
        invite_users=True, pin_messages=True,
    )
    invite = await cl(ExportChatInviteRequest(channel, usage_limit=INVITE_LIMIT))
    return utils.get_peer_id(channel), invite.link


async def create_deal_group(acct, bot_username: str, label: str):
    """Naya private group banata hai. Returns (bot_chat_id, invite_link, deal_id, note).
    note = basic group fail hone ki wajah (agar supergroup fallback hua)."""
    deal_id = uuid.uuid4().hex[:6].upper()
    title = deal_title(label, deal_id)
    note = ""
    if GROUP_MODE == "basic":
        try:
            chat_id, link = await _create_basic(acct.client, bot_username, title)
            return chat_id, link, deal_id, ""
        except Exception as err:
            logging.exception("basic group fail hua, supergroup try kar raha hoon")
            note = f"{type(err).__name__}: {err}"[:300]
    chat_id, link = await _create_super(acct.client, bot_username, title)
    return chat_id, link, deal_id, note


async def create_with_failover(context, bot_username: str, label: str):
    """Free account chunta hai; fail ho to agle account se (max 3 koshish).
    Returns (acct, chat_id, link, deal_id, note)."""
    tried = set()
    last_err = None
    for _ in range(3):
        acct = pick_account(exclude=tried)
        if acct is None:
            break
        tried.add(acct.idx)
        acct.times.append(time.time())  # use ginti mein
        try:
            chat_id, link, deal_id, note = await run_with_reconnect(
                acct, lambda: create_deal_group(acct, bot_username, label))
            return acct, chat_id, link, deal_id, note
        except Exception as err:
            last_err = err
            logging.exception("account #%s se group nahi bana", acct.idx)
            await handle_acct_error(context, acct, err)
    if last_err:
        raise last_err
    raise NoAccountAvailable()


# ======================= TEXTS =======================
def start_text() -> str:
    return (
        f"{e('party')} <b>Welcome to Don Escrow Service</b> {e('party')}\n\n"
        f"{e('shield')} Escrow : @xDonEscrow {e('check')}\n"
        f"{e('info')} Detail : @ZENOx0G {e('check')}\n"
        f"{e('support')} Customer help : @XdonZ {e('check')}"
    )


WELCOME_TEXT = (
    "WELCOME TO GROUP\n\n"
    "START DEAL KARNE KE LIYE\n"
    "/Ready\n\n"
    "PAYMENT KARNE KE LIYE\n"
    "/Deposit\n\n"
    "Payment release karne ke liye\n"
    "/Release\n\n"
    "Payment hold karne ke liye\n"
    "/Hold\n\n"
    "Payment refund karne ke liye\n"
    "/Refund"
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


async def qa(q, *args, **kw):
    """callback answer; query purani ho gayi ho (reconnect mein der lagi) to bhi crash nahi."""
    try:
        await q.answer(*args, **kw)
    except Exception:
        logging.warning("callback answer fail (query purani ho gayi?)")


async def deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    label = DEAL_TYPES[q.data.split(":")[1]]

    if not any_ok():
        now0 = time.time()
        if now0 - context.bot_data.get("last_recheck", 0) > 60:  # 60 sec mein ek baar dobara jodke dekho
            context.bot_data["last_recheck"] = now0
            await recheck_accounts()
    if not any_ok():
        await qa(q, "Group service is temporarily unavailable. Please try again later "
                     "or contact @XdonZ.", show_alert=True)
        now = time.time()
        if now - context.bot_data.get("userbot_alert", 0) > 600:  # 10 min mein ek baar
            context.bot_data["userbot_alert"] = now
            await notify_admin(context, "⚠️ Someone tried to create a deal group, but no owner "
                                        "(userbot) account is working:\n" + accounts_report()
                                        + "\n\nSend /reconnect here after fixing. If the reason says "
                                          "Frozen / AuthKey / session invalid, create a new session "
                                          "string for that account.")
        return

    now = time.time()
    times = [t for t in context.bot_data.get("deal_times", []) if now - t < 3600]
    if len(times) >= MAX_GROUPS_PER_HOUR or (times and now - times[-1] < MIN_GROUP_GAP):
        await qa(q, "The service is busy right now. Please try again in a few minutes.",
                       show_alert=True)
        return
    udeals = context.bot_data.setdefault("user_deals", {})
    mine = [t for t in udeals.get(user.id, []) if now - t < 86400]
    if len(mine) >= MAX_GROUPS_PER_USER_DAY:
        await qa(q, "Daily limit reached. Please try again tomorrow or contact @XdonZ.",
                       show_alert=True)
        return
    if now - context.user_data.get("last_deal", 0) < COOLDOWN:
        await qa(q, "Please wait a minute before creating another group.", show_alert=True)
        return
    if pick_account() is None:
        await qa(q, "The service is busy right now. Please try again in a few minutes.",
                       show_alert=True)
        return
    context.user_data["last_deal"] = now

    await qa(q, "Creating your group...")
    status = await q.message.reply_text(
        f"{e('clock')} Creating your <b>{label}</b> group, please wait...", parse_mode=HTML,
    )

    try:
        bot_username = (await context.bot.get_me()).username
        acct, chat_id, link, deal_id, note = await create_with_failover(context, bot_username, label)
    except Exception as err:
        logging.exception("group creation failed")
        context.user_data["last_deal"] = 0
        name = type(err).__name__
        if isinstance(err, NoAccountAvailable):
            reason = "The service is busy right now. Please try again in a few minutes."
        elif isinstance(err, errors.FloodWaitError):
            mins = max(1, err.seconds // 60)
            reason = f"Too many requests. Please try again after about {mins} minute(s)."
        else:
            reason = "Group could not be created. Please try again or contact @XdonZ."
        extra = ""
        if SHOW_DEBUG:
            extra = f"\n\n<code>[{VERSION}] {html.escape(f'{name}: {err}'[:200])}</code>"
        await status.edit_text(f"{e('cross')} {reason}{extra}", parse_mode=HTML)
        return

    times.append(now)
    context.bot_data["deal_times"] = times
    mine.append(now)
    udeals[user.id] = mine

    await render(lambda icons: status.edit_text(
        f"{e('check')} <b>{label} group is ready!</b>\n\n"
        f"Join using the button below and add the other party.",
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([[btn("Join Group", "link", icons, url=link)]]),
    ))

    mention = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'
    try:
        welcome = await context.bot.send_message(chat_id, WELCOME_TEXT)
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
    st["acct"] = acct.idx
    touch(st)
    if note:
        await notify_admin(context, (
            f"⚠️ {st['title']}: basic group could not be created, a supergroup was created instead "
            f"(owner account will stay visible).\nReason: {note}"))
    is_admin, why = await ensure_bot_admin(context, acct, bot_username, chat_id)
    if not is_admin:
        await notify_admin(context, (
            f"⚠️ Bot is NOT admin in {st['title']} ({why}). It may not see plain messages or photos. "
            f"Disable privacy mode in BotFather (/setprivacy -> Disable), then create a new group."))
    if USERBOT_LEAVE:
        spawn(watch_and_leave(context, chat_id))

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
        await qa(q, "Not allowed.", show_alert=True)
        return

    _, action, cid = q.data.split(":")
    cid = int(cid)
    cid = context.bot_data.get("migrated", {}).get(cid, cid)
    st = deal_state(context, cid)

    if action in ("resume", "close"):
        who = mention_of(q.from_user)
        title = html.escape(st["title"] or str(cid))
        if action == "resume":
            if not st["hold"]:
                await qa(q, "Not on hold.", show_alert=True)
                return
            st["hold"] = False
            touch(st)
            await qa(q, "Resumed.")
            await q.message.edit_text(
                f"{e('check')} <b>Hold removed</b>\n\nDeal: {title}\nBy: {who}", parse_mode=HTML)
            await context.bot.send_message(cid, "Hold removed. The deal can continue.")
        else:
            await qa(q, "Closing the group...")
            await q.message.edit_text(
                f"{e('cross')} <b>Group closed by admin</b>\n\nDeal: {title}\nBy: {who}", parse_mode=HTML)
            await close_group(context.application, cid, "closed by admin")
        return

    if st["paid"]:
        await qa(q, "Already confirmed.", show_alert=True)
        return

    touch(st)
    admin = q.from_user
    who = f'<a href="tg://user?id={admin.id}">{html.escape(admin.first_name or "Admin")}</a>'
    title = html.escape(st["title"] or str(cid))
    st["admin_msg_id"] = None

    if action == "ok":
        st["paid"] = True
        await qa(q, "Confirmed.")
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
        st["acked"] = False
        await qa(q, "Marked as not received.")
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
    chat = update.effective_chat
    text = f"Chat ID: <code>{chat.id}</code>"
    if chat.type == "private":
        text += "\n\nTo receive error alerts here, set this number as LOG_CHAT_ID in Railway Variables."
    elif not is_deal_chat(chat):
        aid = admin_id(context)
        if aid is None:
            text += "\n\nADMIN_GROUP_ID is not set yet."
        elif chat.id == aid:
            text += "\n\nThis is the configured admin group ✅"
        else:
            text += "\n\nThis is NOT the configured admin group ❌ (ADMIN_GROUP_ID is different)."
    await update.message.reply_text(text, parse_mode=HTML)


async def reconnect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reconnect - sabhi userbot accounts ko abhi dobara jodo aur halat batao."""
    chat = update.effective_chat
    if is_deal_chat(chat):
        return
    await update.message.reply_text("Checking the accounts, please wait...")
    await recheck_accounts()
    await update.message.reply_text(accounts_report())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status - bot ki setting check (version, admin group, userbot, payment options)."""
    chat = update.effective_chat
    if is_deal_chat(chat):
        return
    lines = [
        f"Bot version: {VERSION}",
        f"Group mode: {GROUP_MODE}",
        f"Userbot accounts: {sum(1 for a in ACCOUNTS if a.ok)} of {len(ACCOUNTS)} working",
    ]
    aid = admin_id(context)
    if aid is None:
        lines.append("Admin group: NOT SET (add ADMIN_GROUP_ID)")
    else:
        try:
            await context.bot.get_chat(aid)
            me = await context.bot.get_chat_member(aid, context.bot.id)
            lines.append(f"Admin group: OK (bot is {me.status})")
        except ChatMigrated as err:
            context.bot_data["admin_chat"] = err.new_chat_id
            lines.append("Admin group: was upgraded to a supergroup, switched to the new ID automatically")
        except Exception as err:
            lines.append(f"Admin group: ERROR {type(err).__name__}: {err}\n"
                         "  -> This bot must be a member (admin) of the admin group, and ADMIN_GROUP_ID "
                         "must match the number /id shows there.")
    now = time.time()
    for a in ACCOUNTS:
        hour = len([t for t in a.times if now - t < 3600])
        if not a.ok:
            state = f"NOT working ({a.err[:140]})"
        elif a.cool_until > now:
            state = f"resting {int((a.cool_until - now) // 60) + 1} min"
        else:
            state = f"OK, {hour} group(s) in the last hour"
        lines.append(f"  Account #{a.idx}: {state}")
    try:
        me_bot = await context.bot.get_me()
        if me_bot.can_read_all_group_messages:
            lines.append("Privacy mode: OFF (good, bot can read all group messages)")
        else:
            lines.append("Privacy mode: ON (bad) - bot sees only commands/replies unless it is admin. "
                         "BotFather -> /setprivacy -> Disable")
    except Exception:
        pass
    lines.append("Payment options: " + (", ".join(l for l, _ in PAY_OPTIONS) or "NONE (add ADDR_... variables)"))
    lines.append(f"This chat ID: {chat.id}")
    await update.message.reply_text("\n".join(lines))


async def register_join(chat, users, context: ContextTypes.DEFAULT_TYPE):
    """Buyer aur seller join hone par userbot group chhod deta hai."""
    if not chat or "Deal #" not in (chat.title or ""):
        return

    st = deal_state(context, chat.id)
    for m in users:
        if m.is_bot or is_userbot(m.id):
            continue
        st["humans"].add(m.id)

    logging.info("deal %s humans=%s", chat.id, st["humans"])
    if len(st["humans"]) >= 2:
        await try_leave(context, chat.id, st)


def deal_state(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict:
    deals = context.bot_data.setdefault("deals", {})
    st = deals.setdefault(chat_id, {})
    defaults = {
        "humans": set(), "userbot_left": False, "form_msg_id": None,
        "pay_asked": False, "crypto": None, "form_text": "", "title": "",
        "paid": False, "admin_msg_id": None, "payer_id": None,
        "release_asked": False, "awaiting_addr": False, "seller_addr": "",
        "released": False, "payer_locked": False, "leave_tries": 0,
        "acked": False, "members": set(), "last_activity": 0, "delete_at": None,
        "warned": False, "completed": False, "closed": False, "acct": None,
        "hold": False, "refund_asked": False, "awaiting_refund_addr": False,
        "refund_msg_id": None, "refunded": False,
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
    await maybe_leave(context, chat)
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
        "Buyer or Seller, please fill the form above and send it here (reply to the form message).",
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
    if not await send_crypto_menu(context, chat.id, msg.message_id):
        await msg.reply_text("Payment details will be shared here shortly.",
                             reply_to_message_id=msg.message_id)


async def send_crypto_menu(context, chat_id: int, reply_to: int) -> bool:
    """'Which crypto would you like to pay in?' + buttons. False = koi address set nahi."""
    if not PAY_OPTIONS:
        logging.warning("Koi payment address set nahi hai (ADDR_... variables).")
        return False
    rows = []
    for i in range(0, len(PAY_OPTIONS), 2):
        rows.append([("pay:" + c, l) for l, c in PAY_OPTIONS[i:i + 2]])

    def kb(icons):
        return InlineKeyboardMarkup([[btn(l, "bolt", icons, cb=cb) for cb, l in row] for row in rows])

    await render(lambda icons: context.bot.send_message(
        chat_id,
        f"{e('briefcase')} <b>Which crypto would you like to pay in?</b>",
        parse_mode=HTML, reply_markup=kb(icons), reply_to_message_id=reply_to,
    ))
    return True


def mention_of(user) -> str:
    return f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>'


async def send_address(context, chat_id: int, st: dict, reply_to=None):
    """Chuni hui crypto ka ADDRESS message."""
    address = ""
    for _code, (label, addr) in PAY_ADDRESSES.items():
        if label == st["crypto"]:
            address = addr
    await context.bot.send_message(
        chat_id,
        f"ADDRESS : <code>{html.escape(address)}</code>\n\n"
        "Please share your payment screenshot after making the payment.",
        parse_mode=HTML, reply_to_message_id=reply_to,
    )


def is_image(msg) -> bool:
    return bool(msg.photo or (msg.document and (msg.document.mime_type or "").startswith("image/")))


async def handle_proof(msg, chat, st, context):
    """Payment screenshot admin group mein bhejta hai."""
    if is_image(msg) and not st["payer_locked"] and msg.from_user:
        st["payer_id"] = msg.from_user.id  # jisne pehla screenshot bheja wahi payer (buyer)
        st["payer_locked"] = True

    fail_text = "Could not send the screenshot to the admin. Please contact @XdonZ."
    if admin_id(context) is None:
        logging.warning("ADMIN_GROUP_ID set nahi hai, screenshot forward nahi hua.")
        await msg.reply_text(fail_text, reply_to_message_id=msg.message_id)
        return

    try:
        try:
            await admin_call(context, "forward_message", chat.id, msg.message_id)
        except Exception:
            await admin_call(context, "copy_message", chat.id, msg.message_id)
    except Exception as err:
        logging.exception("proof forward failed (ADMIN_GROUP_ID galat ya bot admin group mein nahi)")
        await msg.reply_text(fail_text, reply_to_message_id=msg.message_id)
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(
                    LOG_CHAT_ID, f"Screenshot forward failed in {chat.title}: {type(err).__name__}: {err}"[:3500])
            except Exception:
                pass
        return

    # purana control message hata ke naya bhejo, taaki buttons hamesha sabse neeche rahein
    if st["admin_msg_id"]:
        try:
            await admin_call(context, "delete_message", st["admin_msg_id"])
        except Exception:
            pass

    title = html.escape(st["title"] or chat.title or "")
    summary = html.escape(st["form_text"])[:2500]
    control = None

    async def send(icons):
        nonlocal control
        control = await admin_call(
            context, "send_message",
            f"{e('briefcase')} <b>Payment proof received</b>\n\n"
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

    try:
        await render(send)
    except Exception:
        logging.exception("admin control message failed")
    if control:
        st["admin_msg_id"] = control.message_id
        if not st["acked"]:
            st["acked"] = True
            await msg.reply_text("Received. The admin is verifying the payment.",
                                 reply_to_message_id=msg.message_id)
    else:
        await msg.reply_text(fail_text, reply_to_message_id=msg.message_id)


ADDR_RE = re.compile(r"\b(?:0x[a-fA-F0-9]{40}|[A-Za-z0-9]{26,90})\b")


async def handle_seller_address(msg, chat, st, addr, context):
    """Seller ka address admin group ko bhejta hai (payment release ke liye)."""
    st["seller_addr"] = addr
    st["awaiting_addr"] = False
    fields = parse_form(st["form_text"]) if st["form_text"] else {}
    try:
        sent = await admin_call(
            context, "send_message",
            f"{e('briefcase')} <b>Payment release request</b>\n\n"
            f"Deal: {html.escape(st['title'] or chat.title or '')}\n"
            f"Crypto: {html.escape(st['crypto'] or '-')}\n"
            f"Amount: {html.escape(fields.get('DEAL AMOUNT') or '-')}\n\n"
            f"SELLER ADDRESS : <code>{html.escape(addr)}</code>\n\n"
            f"Please release the payment, then <b>reply to this message</b> with the payment screenshot.",
            parse_mode=HTML,
        )
    except Exception:
        logging.exception("seller address admin ko nahi gaya")
        st["awaiting_addr"] = True  # seller dobara bhej sake
        await msg.reply_text("Could not send your address to the admin. Please contact @XdonZ.",
                             reply_to_message_id=msg.message_id)
        return
    context.bot_data.setdefault("release_map", {})[sent.message_id] = chat.id
    await msg.reply_text("Address received. The admin will release the payment shortly.",
                         reply_to_message_id=msg.message_id)


async def on_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deal group mein koi bhi activity -> delete timer reset."""
    chat = update.effective_chat
    if chat and is_deal_chat(chat):
        touch(deal_state(context, chat.id))


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not is_deal_chat(chat):
        return
    st = deal_state(context, chat.id)
    await maybe_leave(context, chat)

    # 1) bhara hua form
    if msg.text and not st["pay_asked"]:
        up = msg.text.upper()
        if "DEAL AMOUNT" in up and "SELLER" in up and "BUYER" in up:
            await handle_form(msg, chat, st, context)
            return

    # 2) payer ka screenshot (crypto select hone ke baad, admin confirm hone tak)
    if not st["paid"] and (
        st["crypto"] or (is_image(msg) and (st["pay_asked"] or st["form_msg_id"]))
    ):
        await handle_proof(msg, chat, st, context)
        return

    # 3) release (seller) / refund (buyer): wallet address
    if st["paid"] and (st["awaiting_addr"] or st["awaiting_refund_addr"]) and msg.text:
        m = ADDR_RE.search(msg.text)
        if m:
            uid = msg.from_user.id if msg.from_user else None
            await route_address(msg, chat, st, m.group(0), context, uid)


async def start_release(context, chat_id: int, user_id: int):
    """Buyer ke release request ko check karta hai. Returns (ok, error_text)."""
    st = deal_state(context, chat_id)
    if not st["paid"]:
        return False, "Payment is not confirmed yet."
    if st["hold"]:
        return False, "Payment is on hold. Please wait for the admin."
    if st["refund_asked"]:
        return False, "A refund is already in progress."
    if st["payer_id"] and user_id != st["payer_id"]:
        return False, "Only the buyer can release the payment."
    if st["released"]:
        return False, "Payment is already released."
    if st["release_asked"]:
        return False, "Release request is already sent."
    st["release_asked"] = True
    st["awaiting_addr"] = True
    touch(st)
    return True, ""


async def announce_release(context, chat_id: int):
    st = deal_state(context, chat_id)
    await context.bot.send_message(
        chat_id,
        f"{e('check')} <b>Release request received.</b>\n\n"
        f"Seller, please send your {html.escape(st['crypto'] or '')} address here to receive the payment "
        f"(or use /address your_address).",
        parse_mode=HTML,
    )


async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/deposit - payment karne ke liye crypto chuno, phir address milega."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    msg = update.message
    st = deal_state(context, chat.id)
    touch(st)
    if st["completed"]:
        await msg.reply_text("This deal is already completed.")
    elif st["paid"]:
        await msg.reply_text("Payment is already received for this deal.")
    elif st["hold"]:
        await msg.reply_text("Payment is on hold. Please wait for the admin.")
    elif st["crypto"]:
        await send_address(context, chat.id, st, reply_to=msg.message_id)
    else:
        st["pay_asked"] = True
        st["title"] = chat.title or st["title"]
        if not await send_crypto_menu(context, chat.id, msg.message_id):
            await msg.reply_text("Payment details will be shared here shortly.")


async def hold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hold - payment rok do, admin dekhega."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    msg = update.message
    st = deal_state(context, chat.id)
    if st["completed"]:
        await msg.reply_text("This deal is already completed.")
        return
    if not st["crypto"]:
        await msg.reply_text("No payment has been started yet. Use /deposit first.")
        return
    if st["hold"]:
        await msg.reply_text("Payment is already on hold.")
        return
    st["hold"] = True
    st["delete_at"] = None  # hold mein group auto-delete nahi hoga
    st["warned"] = False
    await msg.reply_text("Payment is on hold. The admin will review this deal.")
    title = html.escape(st["title"] or chat.title or "")
    summary = html.escape(st["form_text"])[:2000] or "(form not captured)"
    text = (f"{e('clock')} <b>HOLD requested</b>\n\nDeal: {title}\n"
            f"By: {mention_of(update.effective_user)}\nCrypto: {html.escape(st['crypto'] or '-')}\n\n{summary}")
    try:
        await render(lambda icons: admin_call(
            context, "send_message", text, parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup([[
                btn("Resume Deal", "check", icons, cb=f"adm:resume:{chat.id}"),
                btn("Close Group", "cross", icons, cb=f"adm:close:{chat.id}"),
            ]])))
    except Exception:
        logging.exception("hold notice admin ko nahi gaya")


async def refund_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/refund - payment wapas maango. Buyer apna address deta hai, admin refund karta hai."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    msg = update.message
    st = deal_state(context, chat.id)
    if st["completed"]:
        await msg.reply_text("This deal is already completed.")
    elif not st["paid"]:
        await msg.reply_text("No payment has been received yet, so there is nothing to refund.")
    elif st["hold"]:
        await msg.reply_text("Payment is on hold. Please wait for the admin.")
    elif st["release_asked"]:
        await msg.reply_text("A release is already in progress.")
    elif st["refund_asked"]:
        await msg.reply_text("Refund request is already sent.")
    else:
        st["refund_asked"] = True
        st["awaiting_refund_addr"] = True
        touch(st)
        await context.bot.send_message(
            chat.id,
            f"{e('check')} <b>Refund request received.</b>\n\n"
            f"Buyer, please send your {html.escape(st['crypto'] or '')} address here to receive the refund "
            f"(or use /address your_address).",
            parse_mode=HTML,
        )


async def handle_refund_address(msg, chat, st, addr, context):
    """Buyer ka refund address admin group ko bhejta hai."""
    st["awaiting_refund_addr"] = False
    fields = parse_form(st["form_text"]) if st["form_text"] else {}
    try:
        sent = await admin_call(
            context, "send_message",
            f"{e('briefcase')} <b>Refund request</b>\n\n"
            f"Deal: {html.escape(st['title'] or chat.title or '')}\n"
            f"Crypto: {html.escape(st['crypto'] or '-')}\n"
            f"Amount: {html.escape(fields.get('DEAL AMOUNT') or '-')}\n\n"
            f"BUYER ADDRESS : <code>{html.escape(addr)}</code>\n\n"
            f"If approved, refund the payment, then <b>reply to this message</b> with the payment screenshot.",
            parse_mode=HTML,
        )
    except Exception:
        logging.exception("refund address admin ko nahi gaya")
        st["awaiting_refund_addr"] = True
        await msg.reply_text("Could not send your address to the admin. Please contact @XdonZ.",
                             reply_to_message_id=msg.message_id)
        return
    context.bot_data.setdefault("release_map", {})[sent.message_id] = chat.id
    st["refund_msg_id"] = sent.message_id
    await msg.reply_text("Address received. The admin will review and refund shortly.",
                         reply_to_message_id=msg.message_id)


async def route_address(msg, chat, st, addr, context, user_id) -> bool:
    """Wallet address ko sahi jagah bhejta hai (release = seller, refund = buyer). True = handle hua."""
    if st["paid"] and st["awaiting_addr"]:
        if not (st["payer_id"] and user_id == st["payer_id"]):  # buyer ka message seller address nahi hota
            await handle_seller_address(msg, chat, st, addr, context)
            return True
    if st["paid"] and st["awaiting_refund_addr"]:
        if not st["payer_id"] or user_id == st["payer_id"]:  # refund address buyer ka
            await handle_refund_address(msg, chat, st, addr, context)
            return True
    return False


async def address_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/address <wallet> - privacy mode mein bhi chalta hai (command hamesha bot tak pahunchta hai)."""
    chat = update.effective_chat
    if not is_deal_chat(chat):
        return
    msg = update.message
    st = deal_state(context, chat.id)
    m = ADDR_RE.search(" ".join(context.args or []))
    if not m:
        await msg.reply_text("Usage: /address your_wallet_address")
        return
    uid = update.effective_user.id if update.effective_user else None
    if not await route_address(msg, chat, st, m.group(0), context, uid):
        await msg.reply_text("No address is needed right now.")


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
    if msg.chat_id != admin_id(context):
        return
    ref = msg.reply_to_message
    if not ref:
        return
    deal_chat = context.bot_data.get("release_map", {}).get(ref.message_id)
    if not deal_chat:
        return
    st = deal_state(context, deal_chat)
    refund = st["refund_msg_id"] == ref.message_id
    if st["released"] or st["refunded"]:
        await msg.reply_text("This deal is already completed.")
        return
    await context.bot.copy_message(
        deal_chat, msg.chat_id, msg.message_id,
        caption=f"{e('check')} <b>Payment {'refunded' if refund else 'released'}</b>", parse_mode=HTML,
    )
    st["refunded" if refund else "released"] = True
    st["completed"] = True
    st["delete_at"] = time.time() + COMPLETE_DELETE_SECONDS
    mins = max(1, COMPLETE_DELETE_SECONDS // 60)
    await context.bot.send_message(
        deal_chat,
        f"{e('check')} <b>Deal completed</b>\n\nThis group will be deleted in {mins} minute(s).",
        parse_mode=HTML,
    )
    await msg.reply_text(f"Screenshot sent to the deal group. Deal completed, the group will be deleted in {mins} minute(s).")


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
    touch(st)
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
    if m.from_user and is_userbot(m.from_user.id):
        try:
            await m.delete()  # userbot ne jo add kiya uska "added ..." message hata do
        except Exception:
            pass
    await register_join(update.effective_chat, update.message.new_chat_members, context)


async def on_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Userbot group chhode to uska 'left the group' message hata do."""
    m = update.message
    if m.left_chat_member and is_userbot(m.left_chat_member.id):
        try:
            await m.delete()
        except Exception:
            pass


async def on_created(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Group created' service message hata do (jahan allowed ho)."""
    if is_deal_chat(update.effective_chat):
        try:
            await update.message.delete()
        except Exception:
            pass


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic group supergroup ban jaye to deal ki state naye chat id par le jao."""
    msg = update.message
    if msg.migrate_to_chat_id:
        old, new = msg.chat_id, msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old, new = msg.migrate_from_chat_id, msg.chat_id
    else:
        return
    context.bot_data.setdefault("migrated", {})[old] = new
    if old == admin_id(context):
        context.bot_data["admin_chat"] = new
    deals = context.bot_data.setdefault("deals", {})
    if old in deals and new not in deals:
        deals[new] = deals.pop(old)
    rm = context.bot_data.setdefault("release_map", {})
    for k, v in list(rm.items()):
        if v == old:
            rm[k] = new
    logging.info("chat migrated %s -> %s", old, new)


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
    global ACCOUNTS
    ACCOUNTS = [Acct(i + 1, sess) for i, sess in enumerate(SESSION_LIST)]
    for a in ACCOUNTS:
        a.client = TelegramClient(
            StringSession(a.session), int(API_ID), API_HASH,
            connection_retries=-1, retry_delay=3, auto_reconnect=True,
            request_retries=3, timeout=20,
        )
        try:
            await asyncio.wait_for(a.client.connect(), 60)
            if not await a.client.is_user_authorized():
                a.fatal = True
                raise RuntimeError("session invalid hai ya account logout/freeze hai")
            a.user_id = (await a.client.get_me()).id
            a.ok = True
            logging.info("Account #%s connected.", a.idx)
        except Exception as err:
            a.ok = False
            a.err = f"{type(err).__name__}: {err}"[:300]
            logging.error("Account #%s failed: %s", a.idx, a.err)
        await asyncio.sleep(1)
    spawn(janitor(app))
    spawn(keepalive())
    try:
        await app.bot.set_my_commands(
            [BotCommand("ready", "Start the deal (get the form)"),
             BotCommand("deposit", "Make the payment"),
             BotCommand("release", "Release the payment"),
             BotCommand("hold", "Hold the payment"),
             BotCommand("refund", "Refund the payment"),
             BotCommand("address", "Send your wallet address")],
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception:
        logging.exception("set_my_commands failed")
    try:
        me_bot = await app.bot.get_me()
        if not me_bot.can_read_all_group_messages:
            logging.warning("Privacy mode ON hai (BotFather /setprivacy -> Disable)")
            _aid = app.bot_data.get("admin_chat") or ADMIN_GROUP_ID
            if _aid is not None:
                await app.bot.send_message(
                    _aid, "⚠️ Bot privacy mode is ON. In groups the bot may not see plain messages or "
                          "photos unless it is admin. Fix: BotFather -> /setprivacy -> choose the bot -> Disable, "
                          "then use a NEW group for testing.")
    except Exception:
        logging.exception("privacy check failed")
    aid = app.bot_data.get("admin_chat") or ADMIN_GROUP_ID
    if aid is None:
        logging.warning("ADMIN_GROUP_ID set nahi hai.")
    else:
        try:
            ch = await app.bot.get_chat(aid)
            logging.info("Admin group OK: %s", ch.title)
        except Exception as err:
            logging.error("ADMIN_GROUP_ID problem: %r", err)
    if aid is not None:
        sctx = SimpleNamespace(bot=app.bot, bot_data=app.bot_data)
        try:
            await admin_call(sctx, "send_message",
                             f"✅ Bot {VERSION} started. Admin group connected.\n"
                             f"Userbot accounts working: {sum(1 for a in ACCOUNTS if a.ok)} of {len(ACCOUNTS)}.\n"
                             f"Type /status for details.")
        except Exception as err:
            problem = (f"⚠️ Admin group is NOT reachable ({type(err).__name__}: {err}). "
                       f"Add this bot to the admin group as admin and check ADMIN_GROUP_ID.")
            logging.error(problem)
            if LOG_CHAT_ID:
                try:
                    await app.bot.send_message(LOG_CHAT_ID, problem)
                except Exception:
                    logging.exception("LOG_CHAT_ID message failed")
    elif LOG_CHAT_ID:
        try:
            await app.bot.send_message(LOG_CHAT_ID, "⚠️ ADMIN_GROUP_ID is not set (or not a valid number).")
        except Exception:
            pass
    bad = [a for a in ACCOUNTS if not a.ok]
    if bad and aid is not None:
        try:
            await app.bot.send_message(
                aid, "⚠️ Some owner (userbot) accounts are not working:\n" + accounts_report()
                     + "\n\n" + ("No account is working, new deal groups cannot be created. "
                                   if not any_ok() else "The others will be used. ")
                     + "Fix it and send /reconnect.")
        except Exception:
            pass


async def post_shutdown(app: Application):
    for t in list(BG_TASKS):
        t.cancel()
    for a in ACCOUNTS:
        try:
            await a.client.disconnect()
        except Exception:
            pass


# ======================= MAIN =======================
async def make_session():
    """Userbot account login karke USERBOT_SESSION string print karta hai."""
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    c = TelegramClient(StringSession(), api_id, api_hash)
    await c.start()  # phone number aur OTP puchega
    print("\nUSERBOT_SESSION =", c.session.save())
    print("(Doosre accounts ke liye naam USERBOT_SESSION_2, USERBOT_SESSION_3, ... rakho)")
    await c.disconnect()


def main():
    logging.info("=== Don Escrow bot %s starting ===", VERSION)

    if len(sys.argv) > 1 and sys.argv[1] == "session":
        asyncio.run(make_session())
        return

    missing = [
        name for name, val in [
            ("BOT_TOKEN", BOT_TOKEN), ("API_ID", API_ID),
            ("API_HASH", API_HASH), ("USERBOT_SESSION", "".join(SESSION_LIST)),
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
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^adm:(ok|no|resume|close):-?\d+$"))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
        on_group_message))
    app.add_handler(CommandHandler("release", release_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("deposit", deposit_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("hold", hold_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("refund", refund_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("address", address_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(release_cb, pattern=r"^rel:-?\d+$"))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.REPLY & (filters.PHOTO | filters.Document.IMAGE),
        admin_screenshot), group=1)
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reconnect", reconnect_cmd))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, on_any), group=2)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_migrate))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_CREATED, on_created))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
