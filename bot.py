"""
Rose-style Telegram group management bot
python-telegram-bot==21.6  |  SQLite storage (data restart ke baad bhi safe)
"""
import os
import re
import json
import time
import html
import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ChatPermissions, ReplyParameters)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters,
                          ApplicationHandlerStop)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

# ───────────────────────── CONFIG ─────────────────────────
TOKEN = os.getenv("BOT_TOKEN", "9118700169:AAFThrkpLOlNEm9DCKqKnV8g1MasmUTzzSM")
OWNER_IDS = {123456789}            # apna Telegram user ID (owner ko har command ki permission)
DATA_DIR = os.getenv("DATA_DIR", ".")  # Railway Volume lagao to DATA_DIR=/data rakho
ANON = 1087968824                  # Telegram ka "anonymous admin" id
HTML = ParseMode.HTML

# ───────────────────────── DATABASE ─────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)
DB = sqlite3.connect(os.path.join(DATA_DIR, "rosebot.db"), check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.executescript("""
CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(chat_id, key));
CREATE TABLE IF NOT EXISTS filters(chat_id INTEGER, keyword TEXT, data TEXT, PRIMARY KEY(chat_id, keyword));
CREATE TABLE IF NOT EXISTS notes(chat_id INTEGER, name TEXT, data TEXT, PRIMARY KEY(chat_id, name));
CREATE TABLE IF NOT EXISTS warns(chat_id INTEGER, user_id INTEGER, count INTEGER, reasons TEXT, PRIMARY KEY(chat_id, user_id));
CREATE TABLE IF NOT EXISTS blacklist(chat_id INTEGER, word TEXT, PRIMARY KEY(chat_id, word));
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, name TEXT);
""")
DB.commit()


def db_exec(sql, args=()):
    cur = DB.execute(sql, args)
    DB.commit()
    return cur


def db_all(sql, args=()):
    return DB.execute(sql, args).fetchall()


def db_one(sql, args=()):
    return DB.execute(sql, args).fetchone()


def get_set(chat_id, key, default=None):
    r = db_one("SELECT value FROM settings WHERE chat_id=? AND key=?", (chat_id, key))
    return r["value"] if r else default


def set_set(chat_id, key, value):
    db_exec("INSERT OR REPLACE INTO settings VALUES(?,?,?)", (chat_id, key, str(value)))


def get_json(chat_id, key, default):
    r = get_set(chat_id, key)
    return json.loads(r) if r else default


def set_json(chat_id, key, value):
    set_set(chat_id, key, json.dumps(value))


# ───────────────────────── HELPERS ─────────────────────────
def esc(s):
    return html.escape(s or "")


def mention(uid, name):
    return f'<a href="tg://user?id={uid}">{esc(name) or uid}</a>'


async def say(update, text, **kw):
    return await update.effective_message.reply_text(text, parse_mode=HTML, **kw)


def parse_onoff(a):
    a = (a or "").lower()
    if a in ("on", "yes", "y", "true", "enable"):
        return True
    if a in ("off", "no", "n", "false", "disable"):
        return False
    return None


def parse_time(s):
    m = re.fullmatch(r"(\d+)([smhdw])", (s or "").lower())
    if not m:
        return None
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]


def get_html(m):
    return m.text_html if m.text else (m.caption_html if m.caption else "")


def cmd_rest(msg):
    """Command ke baad ka text (HTML formatting ke saath)."""
    h = get_html(msg).replace("&quot;", '"')
    parts = h.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def split_first(s):
    """Pehla word (ya "quoted phrase") aur baaki text."""
    s = (s or "").strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        if end != -1:
            return s[1:end], s[end + 1:].strip()
    parts = s.split(None, 1)
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def media_of(m):
    if m.photo:
        return "photo", m.photo[-1].file_id
    if m.animation:
        return "animation", m.animation.file_id
    if m.sticker:
        return "sticker", m.sticker.file_id
    if m.document:
        return "document", m.document.file_id
    if m.video:
        return "video", m.video.file_id
    if m.audio:
        return "audio", m.audio.file_id
    if m.voice:
        return "voice", m.voice.file_id
    if m.video_note:
        return "video_note", m.video_note.file_id
    return None


def build_content(msg, rest):
    reply = msg.reply_to_message
    own = media_of(msg)
    if reply and not rest and not own:
        mt = media_of(reply)
        text = get_html(reply)
        if not mt and not text:
            return None
        return {"type": mt[0] if mt else "text", "file_id": mt[1] if mt else None, "text": text}
    if own:
        return {"type": own[0], "file_id": own[1], "text": rest}
    if rest:
        return {"type": "text", "file_id": None, "text": rest}
    return None


BTN_RE = re.compile(r"\[(.+?)\]\(buttonurl://(.+?)\)")


def parse_buttons(text):
    rows = []
    for m in BTN_RE.finditer(text):
        label = html.unescape(m.group(1))
        url = html.unescape(m.group(2))
        same = url.endswith(":same")
        if same:
            url = url[:-5]
        if "://" not in url and not url.startswith("tg:"):
            url = "https://" + url
        btn = InlineKeyboardButton(label, url=url)
        if same and rows:
            rows[-1].append(btn)
        else:
            rows.append([btn])
    if not rows:
        return text, None
    return BTN_RE.sub("", text).strip(), InlineKeyboardMarkup(rows)


def fill(text, user, chat_title, count=None):
    if not text:
        return text
    uname = f"@{user.username}" if user.username else mention(user.id, user.first_name)
    reps = {
        "{first}": esc(user.first_name),
        "{last}": esc(user.last_name),
        "{fullname}": esc(user.full_name),
        "{username}": uname,
        "{mention}": mention(user.id, user.first_name),
        "{id}": str(user.id),
        "{chatname}": esc(chat_title),
        "{count}": str(count) if count is not None else "",
    }
    for k, v in reps.items():
        text = text.replace(k, v)
    return text


async def send_saved(context, chat_id, data, user, chat_title, reply_to=None, count=None):
    text = fill(data.get("text") or "", user, chat_title, count)
    text, markup = parse_buttons(text)
    rp = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
    t = data.get("type", "text")

    async def _send(txt, pm):
        if t == "text":
            return await context.bot.send_message(chat_id, txt or "👇", parse_mode=pm,
                                                  reply_markup=markup, reply_parameters=rp)
        sender = getattr(context.bot, "send_" + t)
        kw = {"reply_markup": markup, "reply_parameters": rp}
        if t not in ("sticker", "video_note"):
            kw.update(caption=txt or None, parse_mode=pm)
        return await sender(chat_id, data["file_id"], **kw)

    try:
        return await _send(text, HTML)
    except TelegramError as e:
        if "parse" in str(e).lower() or "entities" in str(e).lower():
            return await _send(html.unescape(re.sub(r"<[^>]+>", "", text)), None)
        raise


# ───────────────────────── PERMISSIONS ─────────────────────────
_ADMIN_CACHE = {}


async def is_admin_cached(context, chat_id, uid):
    key, now = (chat_id, uid), time.time()
    c = _ADMIN_CACHE.get(key)
    if c and now - c[1] < 60:
        return c[0]
    try:
        m = await context.bot.get_chat_member(chat_id, uid)
        res = m.status in ("administrator", "creator")
    except TelegramError:
        res = False
    _ADMIN_CACHE[key] = (res, now)
    return res


async def check_right(update, context, right=None):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if chat.type == "private":
        await msg.reply_text("This command only works in groups.")
        return False
    if user is None:
        return False
    if user.id in OWNER_IDS or user.id == ANON:
        return True
    try:
        m = await chat.get_member(user.id)
    except TelegramError:
        return False
    if m.status == "creator":
        return True
    if m.status == "administrator":
        if right is None or getattr(m, right, False):
            return True
        await msg.reply_text(f"You need the '{right}' admin right to use this.")
        return False
    await msg.reply_text("Only admins can use this command.")
    return False


async def get_name(context, chat_id, uid):
    try:
        m = await context.bot.get_chat_member(chat_id, uid)
        return m.user.full_name
    except TelegramError:
        r = db_one("SELECT name FROM users WHERE user_id=?", (uid,))
        return r["name"] if r else str(uid)


async def resolve_target(update, context):
    msg = update.effective_message
    args = context.args or []
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name, " ".join(args)
    if args:
        a, uid = args[0], None
        if a.lstrip("-").isdigit():
            uid = int(a)
        elif a.startswith("@"):
            r = db_one("SELECT user_id FROM users WHERE username=?", (a[1:].lower(),))
            uid = r["user_id"] if r else None
        if uid:
            name = await get_name(context, update.effective_chat.id, uid)
            return uid, name, " ".join(args[1:])
    await msg.reply_text("I can't find that user. Reply to their message or give a user ID / @username "
                         "(username tabhi milega jab user ne group mein kabhi message bheja ho).")
    return None


async def target_ok(update, context, uid):
    if uid == context.bot.id:
        await update.effective_message.reply_text("I'm not doing that to myself.")
        return False
    if uid in OWNER_IDS:
        await update.effective_message.reply_text("That's my owner, I can't do that.")
        return False
    try:
        m = await update.effective_chat.get_member(uid)
        if m.status in ("administrator", "creator"):
            await update.effective_message.reply_text("I can't do that to an admin.")
            return False
    except TelegramError:
        pass
    return True


async def default_perms(context, chat_id):
    c = await context.bot.get_chat(chat_id)
    return c.permissions or ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True, can_invite_users=True)


async def apply_mode(context, chat_id, uid, mode):
    if mode == "ban":
        await context.bot.ban_chat_member(chat_id, uid)
        return "banned"
    if mode == "kick":
        await context.bot.ban_chat_member(chat_id, uid)
        await context.bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        return "kicked"
    await context.bot.restrict_chat_member(chat_id, uid, ChatPermissions(can_send_messages=False))
    return "muted"


# ───────────────────────── START / HELP / MISC ─────────────────────────
HELP_TEXT = """<b>📖 Commands</b>

<b>Filters</b> (admin)
/filter [word] [reply] – filter save karo (ya kisi message/media par reply)
/filters – list | /stop [word] – hatao | /stopall – sab hatao (creator)

<b>Notes</b>
/save [name] [text] | /get [name] ya #name | /notes | /clear [name]

<b>Welcome / Goodbye</b>
/setwelcome | /welcome on|off | /resetwelcome
/setgoodbye | /goodbye on|off | /resetgoodbye
/cleanwelcome on|off – purana welcome delete
/cleanservice on|off – join/leave service msg delete

<b>Admin tools</b>
/ban /unban /kick /mute /unmute | /tban /tmute [time]
/warn /warns /resetwarns | /warnlimit [n] | /setwarnmode [ban|kick|mute]
/promote /demote | /pin [loud] /unpin | /purge | /del | /admins

<b>Locks</b>
/lock [type] | /unlock [type] | /locks
Types: sticker gif photo video document audio voice videonote contact location poll game forward url bot all

<b>Blacklist</b>
/addblacklist [word] | /unblacklist [word] | /blacklist | /blacklistmode [delete|warn|mute|ban|kick]

<b>Antiflood</b>
/setflood [n|off] | /flood | /setfloodmode [ban|kick|mute]

<b>Rules</b> /setrules | /rules | /clearrules
<b>Misc</b> /id | /info

<b>Fillings:</b> {first} {last} {fullname} {username} {mention} {id} {chatname} {count}
<b>Buttons:</b> [Button](buttonurl://example.com) – same row ke liye link ke end mein :same"""


async def cmd_start(update, context):
    if update.effective_chat.type != "private":
        await say(update, "I'm alive! Use /help to see what I can do.")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "➕ Add me to your group", url=f"https://t.me/{context.bot.username}?startgroup=true")]])
    await say(update, f"Hi {esc(update.effective_user.first_name)}! 👋\n"
                      "I'm a group management bot – filters, welcome, notes, warns, locks, "
                      "blacklist, antiflood and more.\n\nGroup mein add karo, admin banao aur /help bhejo.",
              reply_markup=kb)


async def cmd_help(update, context):
    await say(update, HELP_TEXT)


async def cmd_id(update, context):
    msg = update.effective_message
    text = f"Chat ID: <code>{update.effective_chat.id}</code>\nYour ID: <code>{update.effective_user.id}</code>"
    if msg.reply_to_message and msg.reply_to_message.from_user:
        text += f"\nReplied user ID: <code>{msg.reply_to_message.from_user.id}</code>"
    await say(update, text)


async def cmd_info(update, context):
    msg = update.effective_message
    u = msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user \
        else update.effective_user
    text = f"<b>User info</b>\nID: <code>{u.id}</code>\nName: {esc(u.full_name)}\n"
    if u.username:
        text += f"Username: @{u.username}\n"
    text += f"Profile: {mention(u.id, 'link')}"
    await say(update, text)


async def cmd_admins(update, context):
    if update.effective_chat.type == "private":
        return
    admins = await update.effective_chat.get_administrators()
    lines = []
    for a in admins:
        if a.user.is_bot:
            continue
        lines.append(("👑 " if a.status == "creator" else "• ") + esc(a.user.full_name))
    await say(update, "<b>Admins:</b>\n" + "\n".join(lines))


# ───────────────────────── FILTERS ─────────────────────────
async def cmd_filter(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    msg, chat = update.effective_message, update.effective_chat
    kw, rest = split_first(cmd_rest(msg))
    if not kw:
        await msg.reply_text("Usage: /filter [keyword] [reply text] – ya kisi message par reply karke /filter [keyword]")
        return
    data = build_content(msg, rest)
    if not data:
        await msg.reply_text("Reply text do ya kisi message/media par reply karo.")
        return
    kw = html.unescape(kw).lower()
    db_exec("INSERT OR REPLACE INTO filters VALUES(?,?,?)", (chat.id, kw, json.dumps(data)))
    await say(update, f"Saved filter '<code>{esc(kw)}</code>'.")


async def cmd_filters(update, context):
    chat = update.effective_chat
    if chat.type == "private":
        return
    rows = db_all("SELECT keyword FROM filters WHERE chat_id=? ORDER BY keyword", (chat.id,))
    if not rows:
        await say(update, "No filters in this chat.")
        return
    await say(update, f"<b>Filters in {esc(chat.title)}:</b>\n" +
              "\n".join(f"• <code>{esc(r['keyword'])}</code>" for r in rows))


async def cmd_stop(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    kw, _ = split_first(cmd_rest(update.effective_message))
    kw = html.unescape(kw).lower()
    if not kw:
        await say(update, "Usage: /stop [keyword]")
        return
    cur = db_exec("DELETE FROM filters WHERE chat_id=? AND keyword=?", (chat.id, kw))
    await say(update, "Filter removed." if cur.rowcount else "No such filter.")


async def cmd_stopall(update, context):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == "private":
        return
    try:
        m = await chat.get_member(user.id)
    except TelegramError:
        return
    if m.status != "creator" and user.id not in OWNER_IDS:
        await say(update, "Only the chat creator can remove all filters.")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Yes, delete all", callback_data="stopall:yes"),
                                InlineKeyboardButton("Cancel", callback_data="stopall:no")]])
    await say(update, "Delete ALL filters in this chat? This can't be undone.", reply_markup=kb)


async def cb_stopall(update, context):
    q = update.callback_query
    chat = q.message.chat
    try:
        m = await chat.get_member(q.from_user.id)
    except TelegramError:
        return
    if m.status != "creator" and q.from_user.id not in OWNER_IDS:
        await q.answer("Only the chat creator can do this.", show_alert=True)
        return
    if q.data == "stopall:yes":
        db_exec("DELETE FROM filters WHERE chat_id=?", (chat.id,))
        await q.edit_message_text("All filters deleted.")
    else:
        await q.edit_message_text("Cancelled.")
    await q.answer()


# ───────────────────────── NOTES ─────────────────────────
async def send_note(update, context, name):
    chat, msg = update.effective_chat, update.effective_message
    row = db_one("SELECT data FROM notes WHERE chat_id=? AND name=?", (chat.id, name))
    if not row:
        await msg.reply_text("Note not found.")
        return
    reply_to = msg.reply_to_message.message_id if msg.reply_to_message else msg.message_id
    await send_saved(context, chat.id, json.loads(row["data"]), update.effective_user,
                     chat.title, reply_to=reply_to)


async def cmd_save(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    msg, chat = update.effective_message, update.effective_chat
    name, rest = split_first(cmd_rest(msg))
    if not name:
        await msg.reply_text("Usage: /save [name] [text] – ya kisi message par reply karke /save [name]")
        return
    data = build_content(msg, rest)
    if not data:
        await msg.reply_text("Note ka content do ya kisi message par reply karo.")
        return
    name = html.unescape(name).lower().lstrip("#")
    db_exec("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (chat.id, name, json.dumps(data)))
    await say(update, f"Saved note '<code>{esc(name)}</code>'. Get it with /get {esc(name)} or #{esc(name)}")


async def cmd_get(update, context):
    if update.effective_chat.type == "private":
        return
    if not context.args:
        await say(update, "Usage: /get [name]")
        return
    await send_note(update, context, context.args[0].lower().lstrip("#"))


async def cmd_notes(update, context):
    chat = update.effective_chat
    if chat.type == "private":
        return
    rows = db_all("SELECT name FROM notes WHERE chat_id=? ORDER BY name", (chat.id,))
    if not rows:
        await say(update, "No notes in this chat.")
        return
    await say(update, f"<b>Notes in {esc(chat.title)}:</b>\n" +
              "\n".join(f"• <code>#{esc(r['name'])}</code>" for r in rows))


async def cmd_clear(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    if not context.args:
        await say(update, "Usage: /clear [name]")
        return
    cur = db_exec("DELETE FROM notes WHERE chat_id=? AND name=?",
                  (update.effective_chat.id, context.args[0].lower().lstrip("#")))
    await say(update, "Note deleted." if cur.rowcount else "No such note.")


# ───────────────────────── WELCOME / GOODBYE ─────────────────────────
DEFAULTS = {
    "welcome": {"type": "text", "file_id": None, "text": "Hey {first}, how are you?"},
    "goodbye": {"type": "text", "file_id": None, "text": "Sad to see you leave, {first}."},
}


def greet_show(kind):
    async def h(update, context):
        if not await check_right(update, context, "can_change_info"):
            return
        chat, msg = update.effective_chat, update.effective_message
        if context.args:
            v = parse_onoff(context.args[0])
            if v is None:
                await say(update, f"Use: /{kind} on | off")
                return
            set_set(chat.id, f"{kind}_on", "1" if v else "0")
            await say(update, f"{kind.capitalize()} is now <b>{'ON' if v else 'OFF'}</b>.")
            return
        on = get_set(chat.id, f"{kind}_on", "1" if kind == "welcome" else "0") == "1"
        await say(update, f"{kind.capitalize()} is <b>{'ON' if on else 'OFF'}</b>. Current message:")
        data = get_json(chat.id, f"{kind}_data", DEFAULTS[kind])
        await send_saved(context, chat.id, data, update.effective_user, chat.title)
    return h


def greet_set(kind):
    async def h(update, context):
        if not await check_right(update, context, "can_change_info"):
            return
        msg, chat = update.effective_message, update.effective_chat
        data = build_content(msg, cmd_rest(msg))
        if not data:
            await msg.reply_text(f"Usage: /set{kind} [text] – ya kisi message par reply karo. "
                                 "Fillings ke liye /help dekho.")
            return
        set_json(chat.id, f"{kind}_data", data)
        await say(update, f"Custom {kind} message saved!")
    return h


def greet_reset(kind):
    async def h(update, context):
        if not await check_right(update, context, "can_change_info"):
            return
        db_exec("DELETE FROM settings WHERE chat_id=? AND key=?",
                (update.effective_chat.id, f"{kind}_data"))
        await say(update, f"{kind.capitalize()} message reset to default.")
    return h


def toggle(cmd, key, label):
    async def h(update, context):
        if not await check_right(update, context, "can_change_info"):
            return
        chat = update.effective_chat
        v = parse_onoff(context.args[0]) if context.args else None
        if v is None:
            cur = get_set(chat.id, key, "0") == "1"
            await say(update, f"{label} is <b>{'ON' if cur else 'OFF'}</b>. Use /{cmd} on | off")
            return
        set_set(chat.id, key, "1" if v else "0")
        await say(update, f"{label} is now <b>{'ON' if v else 'OFF'}</b>.")
    return h


async def on_join(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if get_set(chat.id, "cleanservice", "0") == "1":
        try:
            await msg.delete()
        except TelegramError:
            pass
    locks = get_json(chat.id, "locks", [])
    for member in msg.new_chat_members:
        if member.id == context.bot.id:
            await context.bot.send_message(
                chat.id, "Thanks for adding me! Mujhe admin banao (delete, ban, pin rights ke saath) "
                         "aur /help bhejo.")
            continue
        adder = msg.from_user
        if member.is_bot and "bot" in locks and adder and not await is_admin_cached(context, chat.id, adder.id):
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
            except TelegramError:
                pass
            continue
        if get_set(chat.id, "welcome_on", "1") != "1":
            continue
        data = get_json(chat.id, "welcome_data", DEFAULTS["welcome"])
        try:
            count = await context.bot.get_chat_member_count(chat.id)
            if get_set(chat.id, "cleanwelcome", "0") == "1":
                last = get_set(chat.id, "last_welcome")
                if last:
                    try:
                        await context.bot.delete_message(chat.id, int(last))
                    except TelegramError:
                        pass
            sent = await send_saved(context, chat.id, data, member, chat.title, count=count)
            set_set(chat.id, "last_welcome", sent.message_id)
        except TelegramError as e:
            logging.warning("welcome failed: %s", e)


async def on_left(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if get_set(chat.id, "cleanservice", "0") == "1":
        try:
            await msg.delete()
        except TelegramError:
            pass
    u = msg.left_chat_member
    if not u or u.id == context.bot.id:
        return
    if get_set(chat.id, "goodbye_on", "0") != "1":
        return
    data = get_json(chat.id, "goodbye_data", DEFAULTS["goodbye"])
    try:
        await send_saved(context, chat.id, data, u, chat.title)
    except TelegramError as e:
        logging.warning("goodbye failed: %s", e)


# ───────────────────────── RULES ─────────────────────────
async def cmd_setrules(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    msg = update.effective_message
    rest = cmd_rest(msg)
    if not rest and msg.reply_to_message:
        rest = get_html(msg.reply_to_message)
    if not rest:
        await msg.reply_text("Usage: /setrules [text] – ya kisi message par reply karo.")
        return
    set_set(update.effective_chat.id, "rules", rest)
    await say(update, "Rules saved.")


async def cmd_rules(update, context):
    if update.effective_chat.type == "private":
        return
    rules = get_set(update.effective_chat.id, "rules")
    if not rules:
        await say(update, "No rules have been set yet.")
        return
    await say(update, f"<b>Rules of {esc(update.effective_chat.title)}:</b>\n\n{rules}")


async def cmd_clearrules(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    db_exec("DELETE FROM settings WHERE chat_id=? AND key='rules'", (update.effective_chat.id,))
    await say(update, "Rules cleared.")


# ───────────────────────── BAN / MUTE / KICK ─────────────────────────
def moderate(kind):
    past = {"ban": "banned", "tban": "banned", "unban": "unbanned", "kick": "kicked",
            "mute": "muted", "tmute": "muted", "unmute": "unmuted"}[kind]

    async def handler(update, context):
        if not await check_right(update, context, "can_restrict_members"):
            return
        r = await resolve_target(update, context)
        if not r:
            return
        uid, name, rest = r
        chat = update.effective_chat
        if kind not in ("unban", "unmute") and not await target_ok(update, context, uid):
            return
        until, label, rest = None, "", rest.strip()
        if kind in ("tban", "tmute"):
            first, _, rest = rest.partition(" ")
            secs = parse_time(first)
            if not secs:
                await say(update, "Duration do: 30m, 2h, 1d ya 1w.")
                return
            until = datetime.now(timezone.utc) + timedelta(seconds=secs)
            label = f" for {esc(first)}"
        try:
            if kind in ("ban", "tban"):
                await context.bot.ban_chat_member(chat.id, uid, until_date=until)
            elif kind == "unban":
                await context.bot.unban_chat_member(chat.id, uid, only_if_banned=True)
            elif kind == "kick":
                await apply_mode(context, chat.id, uid, "kick")
            elif kind in ("mute", "tmute"):
                await context.bot.restrict_chat_member(chat.id, uid, ChatPermissions(can_send_messages=False),
                                                       until_date=until)
            elif kind == "unmute":
                await context.bot.restrict_chat_member(chat.id, uid, await default_perms(context, chat.id))
        except TelegramError as e:
            await say(update, f"Failed: {esc(e.message)}")
            return
        text = f"{mention(uid, name)} has been {past}{label}!"
        if rest.strip():
            text += f"\nReason: {esc(rest.strip())}"
        await say(update, text)
    return handler


# ───────────────────────── WARNS ─────────────────────────
async def add_warn(context, chat_id, uid, name, reason=""):
    row = db_one("SELECT count, reasons FROM warns WHERE chat_id=? AND user_id=?", (chat_id, uid))
    count = (row["count"] if row else 0) + 1
    reasons = json.loads(row["reasons"]) if row else []
    if reason:
        reasons.append(reason)
    limit = int(get_set(chat_id, "warn_limit", "3"))
    mode = get_set(chat_id, "warn_mode", "ban")
    who = mention(uid, name)
    if count >= limit:
        db_exec("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, uid))
        try:
            done = await apply_mode(context, chat_id, uid, mode)
        except TelegramError as e:
            return f"Warn limit reached but I couldn't act: {esc(e.message)}", None
        return f"{who} reached {limit}/{limit} warnings and has been {done}!", None
    db_exec("INSERT OR REPLACE INTO warns VALUES(?,?,?,?)", (chat_id, uid, count, json.dumps(reasons)))
    text = f"{who} has {count}/{limit} warnings."
    if reason:
        text += f"\nReason: {esc(reason)}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Remove warn (admin only)",
                                                     callback_data=f"rmwarn:{uid}")]])
    return text, kb


async def cmd_warn(update, context):
    if not await check_right(update, context, "can_restrict_members"):
        return
    r = await resolve_target(update, context)
    if not r:
        return
    uid, name, reason = r
    if not await target_ok(update, context, uid):
        return
    text, kb = await add_warn(context, update.effective_chat.id, uid, name, reason.strip())
    await say(update, text, reply_markup=kb)


async def cb_rmwarn(update, context):
    q = update.callback_query
    chat = q.message.chat
    uid = int(q.data.split(":")[1])
    try:
        m = await chat.get_member(q.from_user.id)
    except TelegramError:
        return
    ok = q.from_user.id in OWNER_IDS or m.status == "creator" or \
        (m.status == "administrator" and m.can_restrict_members)
    if not ok:
        await q.answer("Only admins can do this.", show_alert=True)
        return
    row = db_one("SELECT count, reasons FROM warns WHERE chat_id=? AND user_id=?", (chat.id, uid))
    if row:
        newc = row["count"] - 1
        if newc <= 0:
            db_exec("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat.id, uid))
        else:
            reasons = json.loads(row["reasons"])
            if reasons:
                reasons.pop()
            db_exec("UPDATE warns SET count=?, reasons=? WHERE chat_id=? AND user_id=?",
                    (newc, json.dumps(reasons), chat.id, uid))
    await q.edit_message_text(f"Warn removed by {mention(q.from_user.id, q.from_user.first_name)}.",
                              parse_mode=HTML)
    await q.answer()


async def cmd_warns(update, context):
    if update.effective_chat.type == "private":
        return
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        uid, name = u.id, u.full_name
    else:
        uid, name = update.effective_user.id, update.effective_user.full_name
    chat = update.effective_chat
    row = db_one("SELECT count, reasons FROM warns WHERE chat_id=? AND user_id=?", (chat.id, uid))
    limit = get_set(chat.id, "warn_limit", "3")
    if not row:
        await say(update, f"{mention(uid, name)} has no warnings.")
        return
    text = f"{mention(uid, name)} has {row['count']}/{limit} warnings."
    reasons = json.loads(row["reasons"])
    if reasons:
        text += "\n" + "\n".join(f"{i}. {esc(r)}" for i, r in enumerate(reasons, 1))
    await say(update, text)


async def cmd_resetwarns(update, context):
    if not await check_right(update, context, "can_restrict_members"):
        return
    r = await resolve_target(update, context)
    if not r:
        return
    uid, name, _ = r
    db_exec("DELETE FROM warns WHERE chat_id=? AND user_id=?", (update.effective_chat.id, uid))
    await say(update, f"Warnings of {mention(uid, name)} have been reset.")


async def cmd_warnlimit(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    if context.args and context.args[0].isdigit() and int(context.args[0]) >= 1:
        set_set(chat.id, "warn_limit", int(context.args[0]))
        await say(update, f"Warn limit set to {int(context.args[0])}.")
    else:
        await say(update, f"Current warn limit: {get_set(chat.id, 'warn_limit', '3')}. Use /warnlimit [number]")


async def cmd_setwarnmode(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    if context.args and context.args[0].lower() in ("ban", "kick", "mute"):
        set_set(chat.id, "warn_mode", context.args[0].lower())
        await say(update, f"Warn mode set to {context.args[0].lower()}.")
    else:
        await say(update, f"Current warn mode: {get_set(chat.id, 'warn_mode', 'ban')}. Use /setwarnmode ban|kick|mute")


# ───────────────────────── ADMIN TOOLS ─────────────────────────
async def cmd_pin(update, context):
    if not await check_right(update, context, "can_pin_messages"):
        return
    msg = update.effective_message
    if not msg.reply_to_message:
        await say(update, "Reply to a message to pin it.")
        return
    loud = bool(context.args) and context.args[0].lower() in ("loud", "notify")
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, msg.reply_to_message.message_id,
                                           disable_notification=not loud)
    except TelegramError as e:
        await say(update, f"Failed: {esc(e.message)}")


async def cmd_unpin(update, context):
    if not await check_right(update, context, "can_pin_messages"):
        return
    msg = update.effective_message
    try:
        await context.bot.unpin_chat_message(
            update.effective_chat.id,
            message_id=msg.reply_to_message.message_id if msg.reply_to_message else None)
    except TelegramError as e:
        await say(update, f"Failed: {esc(e.message)}")


async def cmd_purge(update, context):
    if not await check_right(update, context, "can_delete_messages"):
        return
    msg, chat = update.effective_message, update.effective_chat
    if not msg.reply_to_message:
        await say(update, "Reply to the message you want to start purging from.")
        return
    ids = list(range(msg.reply_to_message.message_id, msg.message_id + 1))[:2000]
    for i in range(0, len(ids), 100):
        try:
            await context.bot.delete_messages(chat.id, ids[i:i + 100])
        except TelegramError:
            pass
    done = await context.bot.send_message(chat.id, "Purge complete.")
    await asyncio.sleep(3)
    try:
        await done.delete()
    except TelegramError:
        pass


async def cmd_del(update, context):
    if not await check_right(update, context, "can_delete_messages"):
        return
    msg = update.effective_message
    if not msg.reply_to_message:
        await say(update, "Reply to the message you want to delete.")
        return
    try:
        await msg.reply_to_message.delete()
        await msg.delete()
    except TelegramError as e:
        await say(update, f"Failed: {esc(e.message)}")


async def cmd_promote(update, context):
    if not await check_right(update, context, "can_promote_members"):
        return
    r = await resolve_target(update, context)
    if not r:
        return
    uid, name, _ = r
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, uid, can_change_info=True, can_delete_messages=True,
            can_invite_users=True, can_restrict_members=True, can_pin_messages=True,
            can_manage_video_chats=True)
    except TelegramError as e:
        await say(update, f"Failed: {esc(e.message)}")
        return
    await say(update, f"{mention(uid, name)} has been promoted!")


async def cmd_demote(update, context):
    if not await check_right(update, context, "can_promote_members"):
        return
    r = await resolve_target(update, context)
    if not r:
        return
    uid, name, _ = r
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, uid, can_change_info=False, can_delete_messages=False,
            can_invite_users=False, can_restrict_members=False, can_pin_messages=False,
            can_manage_video_chats=False, can_promote_members=False)
    except TelegramError as e:
        await say(update, f"Failed: {esc(e.message)}")
        return
    await say(update, f"{mention(uid, name)} has been demoted.")


# ───────────────────────── LOCKS ─────────────────────────
LOCK_TYPES = ["sticker", "gif", "photo", "video", "document", "audio", "voice", "videonote",
              "contact", "location", "poll", "game", "forward", "url", "bot", "all"]


def violates(msg, locks):
    if "all" in locks:
        return True
    checks = {
        "sticker": msg.sticker, "gif": msg.animation, "photo": msg.photo, "video": msg.video,
        "document": msg.document, "audio": msg.audio, "voice": msg.voice,
        "videonote": msg.video_note, "contact": msg.contact, "poll": msg.poll, "game": msg.game,
        "location": msg.location or msg.venue,
    }
    for t in locks:
        if t == "url":
            ents = list(msg.entities or []) + list(msg.caption_entities or [])
            if any(e.type in ("url", "text_link") for e in ents):
                return True
        elif t == "forward":
            if msg.forward_origin:
                return True
        elif checks.get(t):
            return True
    return False


def lock_cmd(lock):
    async def h(update, context):
        if not await check_right(update, context, "can_change_info"):
            return
        chat = update.effective_chat
        types = [a.lower() for a in (context.args or [])]
        bad = [t for t in types if t not in LOCK_TYPES]
        if not types or bad:
            await say(update, "Usage: /{} [type]\nTypes: {}".format("lock" if lock else "unlock",
                                                                     " ".join(LOCK_TYPES)))
            return
        cur = set(get_json(chat.id, "locks", []))
        cur = cur | set(types) if lock else cur - set(types)
        set_json(chat.id, "locks", sorted(cur))
        await say(update, f"{'Locked' if lock else 'Unlocked'}: <code>{esc(' '.join(types))}</code>")
    return h


async def cmd_locks(update, context):
    if update.effective_chat.type == "private":
        return
    cur = get_json(update.effective_chat.id, "locks", [])
    lines = [f"{'🔒' if t in cur else '🔓'} {t}" for t in LOCK_TYPES]
    await say(update, "<b>Locks:</b>\n" + "\n".join(lines))


# ───────────────────────── BLACKLIST ─────────────────────────
def plain_rest(msg):
    parts = (msg.text or "").split(None, 1)
    return parts[1] if len(parts) > 1 else ""


async def cmd_addblacklist(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    words = [w.strip().lower() for w in plain_rest(update.effective_message).split("\n") if w.strip()]
    if not words:
        await say(update, "Usage: /addblacklist [word] (har line mein ek word/phrase)")
        return
    for w in words:
        db_exec("INSERT OR IGNORE INTO blacklist VALUES(?,?)", (update.effective_chat.id, w))
    await say(update, "Added to blacklist: " + ", ".join(f"<code>{esc(w)}</code>" for w in words))


async def cmd_unblacklist(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    words = [w.strip().lower() for w in plain_rest(update.effective_message).split("\n") if w.strip()]
    if not words:
        await say(update, "Usage: /unblacklist [word]")
        return
    for w in words:
        db_exec("DELETE FROM blacklist WHERE chat_id=? AND word=?", (update.effective_chat.id, w))
    await say(update, "Removed from blacklist.")


async def cmd_blacklist(update, context):
    chat = update.effective_chat
    if chat.type == "private":
        return
    rows = db_all("SELECT word FROM blacklist WHERE chat_id=? ORDER BY word", (chat.id,))
    if not rows:
        await say(update, "No blacklisted words.")
        return
    await say(update, f"<b>Blacklist</b> (mode: {get_set(chat.id, 'bl_mode', 'delete')}):\n" +
              "\n".join(f"• <code>{esc(r['word'])}</code>" for r in rows))


async def cmd_blacklistmode(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    if context.args and context.args[0].lower() in ("delete", "warn", "mute", "ban", "kick"):
        set_set(chat.id, "bl_mode", context.args[0].lower())
        await say(update, f"Blacklist mode set to {context.args[0].lower()}.")
    else:
        await say(update, "Use /blacklistmode delete|warn|mute|ban|kick")


# ───────────────────────── ANTIFLOOD ─────────────────────────
async def cmd_setflood(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    a = (context.args[0].lower() if context.args else "")
    if a in ("off", "no", "0"):
        set_set(chat.id, "flood_limit", 0)
        await say(update, "Antiflood disabled.")
    elif a.isdigit() and int(a) >= 3:
        set_set(chat.id, "flood_limit", int(a))
        await say(update, f"Antiflood set: {int(a)} consecutive messages = action.")
    else:
        await say(update, "Usage: /setflood [number ≥ 3 | off]")


async def cmd_flood(update, context):
    chat = update.effective_chat
    if chat.type == "private":
        return
    lim = int(get_set(chat.id, "flood_limit", "0"))
    await say(update, "Antiflood is OFF." if not lim else
              f"Antiflood: {lim} consecutive messages → {get_set(chat.id, 'flood_mode', 'mute')}.")


async def cmd_setfloodmode(update, context):
    if not await check_right(update, context, "can_change_info"):
        return
    chat = update.effective_chat
    if context.args and context.args[0].lower() in ("ban", "kick", "mute"):
        set_set(chat.id, "flood_mode", context.args[0].lower())
        await say(update, f"Flood mode set to {context.args[0].lower()}.")
    else:
        await say(update, "Use /setfloodmode ban|kick|mute")


# ───────────────────────── MESSAGE WATCHERS ─────────────────────────
_SEEN = {}


async def track(update, context):
    u = update.effective_user
    if u and u.username and _SEEN.get(u.id) != u.username:
        _SEEN[u.id] = u.username
        db_exec("INSERT OR REPLACE INTO users VALUES(?,?,?)", (u.id, u.username.lower(), u.full_name))


async def guard(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not user or chat.type == "private":
        return
    if user.id in OWNER_IDS or user.id in (ANON, 777000) or msg.sender_chat:
        return
    if await is_admin_cached(context, chat.id, user.id):
        return

    # locks
    locks = get_json(chat.id, "locks", [])
    if locks and violates(msg, locks):
        try:
            await msg.delete()
        except TelegramError:
            pass
        raise ApplicationHandlerStop

    # blacklist
    text = msg.text or msg.caption or ""
    if text:
        for r in db_all("SELECT word FROM blacklist WHERE chat_id=?", (chat.id,)):
            if re.search(r"(?<!\w)" + re.escape(r["word"]) + r"(?!\w)", text, re.I):
                try:
                    await msg.delete()
                except TelegramError:
                    pass
                mode = get_set(chat.id, "bl_mode", "delete")
                if mode == "warn":
                    t, kb = await add_warn(context, chat.id, user.id, user.full_name, "Blacklisted word")
                    await context.bot.send_message(chat.id, t, parse_mode=HTML, reply_markup=kb)
                elif mode in ("ban", "kick", "mute"):
                    try:
                        done = await apply_mode(context, chat.id, user.id, mode)
                        await context.bot.send_message(
                            chat.id, f"{mention(user.id, user.full_name)} has been {done} (blacklisted word).",
                            parse_mode=HTML)
                    except TelegramError:
                        pass
                raise ApplicationHandlerStop

    # antiflood
    limit = int(get_set(chat.id, "flood_limit", "0"))
    if limit and update.message:
        fl = context.bot_data.setdefault("flood", {})
        last_uid, count = fl.get(chat.id, (None, 0))
        count = count + 1 if last_uid == user.id else 1
        fl[chat.id] = (user.id, count)
        if count >= limit:
            fl[chat.id] = (None, 0)
            try:
                done = await apply_mode(context, chat.id, user.id, get_set(chat.id, "flood_mode", "mute"))
                await context.bot.send_message(
                    chat.id, f"🚫 Flood detected! {mention(user.id, user.full_name)} has been {done}.",
                    parse_mode=HTML)
            except TelegramError:
                pass
            raise ApplicationHandlerStop


async def reply_handler(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not user or chat.type == "private":
        return
    text = msg.text or msg.caption
    if not text:
        return
    reply_to = msg.reply_to_message.message_id if msg.reply_to_message else msg.message_id

    # notes: #name
    m = re.match(r"#(\w+)", text.strip())
    if m:
        row = db_one("SELECT data FROM notes WHERE chat_id=? AND name=?", (chat.id, m.group(1).lower()))
        if row:
            await send_saved(context, chat.id, json.loads(row["data"]), user, chat.title, reply_to=reply_to)
            return

    # filters: sabse lamba matching keyword
    best = None
    for r in db_all("SELECT keyword, data FROM filters WHERE chat_id=?", (chat.id,)):
        kw = r["keyword"]
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text, re.I):
            if best is None or len(kw) > len(best["keyword"]):
                best = r
    if best:
        try:
            await send_saved(context, chat.id, json.loads(best["data"]), user, chat.title, reply_to=reply_to)
        except TelegramError as e:
            logging.warning("filter send failed: %s", e)


async def caption_router(update, context):
    m = re.match(r"/(\w+)", update.effective_message.caption or "")
    fn = {"filter": cmd_filter, "save": cmd_save, "setwelcome": greet_set("welcome"),
          "setgoodbye": greet_set("goodbye"), "setrules": cmd_setrules}.get(m.group(1).lower() if m else "")
    if fn:
        await fn(update, context)


async def on_error(update, context):
    logging.error("Error while handling update", exc_info=context.error)


# ───────────────────────── MAIN ─────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    commands = {
        "start": cmd_start, "help": cmd_help, "id": cmd_id, "info": cmd_info, "admins": cmd_admins,
        "filter": cmd_filter, "filters": cmd_filters, "stop": cmd_stop, "stopall": cmd_stopall,
        "save": cmd_save, "get": cmd_get, "notes": cmd_notes, "saved": cmd_notes, "clear": cmd_clear,
        "welcome": greet_show("welcome"), "setwelcome": greet_set("welcome"),
        "resetwelcome": greet_reset("welcome"),
        "goodbye": greet_show("goodbye"), "setgoodbye": greet_set("goodbye"),
        "resetgoodbye": greet_reset("goodbye"),
        "cleanwelcome": toggle("cleanwelcome", "cleanwelcome", "Clean welcome"),
        "cleanservice": toggle("cleanservice", "cleanservice", "Clean service messages"),
        "setrules": cmd_setrules, "rules": cmd_rules, "clearrules": cmd_clearrules,
        "ban": moderate("ban"), "unban": moderate("unban"), "kick": moderate("kick"),
        "mute": moderate("mute"), "unmute": moderate("unmute"),
        "tban": moderate("tban"), "tmute": moderate("tmute"),
        "warn": cmd_warn, "warns": cmd_warns, "resetwarns": cmd_resetwarns,
        "warnlimit": cmd_warnlimit, "setwarnmode": cmd_setwarnmode,
        "pin": cmd_pin, "unpin": cmd_unpin, "purge": cmd_purge, "del": cmd_del,
        "promote": cmd_promote, "demote": cmd_demote,
        "lock": lock_cmd(True), "unlock": lock_cmd(False), "locks": cmd_locks,
        "addblacklist": cmd_addblacklist, "unblacklist": cmd_unblacklist,
        "blacklist": cmd_blacklist, "blacklistmode": cmd_blacklistmode,
        "setflood": cmd_setflood, "flood": cmd_flood, "setfloodmode": cmd_setfloodmode,
    }
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(MessageHandler(
        filters.CaptionRegex(r"^/(filter|save|setwelcome|setgoodbye|setrules)(@\w+)?(\s|$)"), caption_router))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left))
    app.add_handler(CallbackQueryHandler(cb_stopall, pattern=r"^stopall:"))
    app.add_handler(CallbackQueryHandler(cb_rmwarn, pattern=r"^rmwarn:\d+$"))

    app.add_handler(MessageHandler(filters.ChatType.GROUPS, track), group=-2)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard), group=1)
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.StatusUpdate.ALL, reply_handler), group=2)

    app.add_error_handler(on_error)
    logging.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
