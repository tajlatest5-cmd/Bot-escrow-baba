import asyncio
import html
import json
import logging
import os
import time

from telegram import BotCommand, Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    Defaults, MessageHandler, filters,
)

# ================= SETTINGS =================
TOKEN = os.getenv("BOT_TOKEN", "9080234676:AAEllP2SrA0aMF0y1y7V39vFKkKyrsS94BY")
ADMIN_IDS = [7054168366]          # admins (aur IDs yahan add karo)
GROUP_ID = -1004418593335                   # deal cards is group me post hon (e.g. -100123...), None = same chat
FEE_PERCENT = 3                   # user ke /sell wali NFT deal par fee %
ADMIN_FEE = 0                     # admin ke /addnft par fee % (0 = koi fee nahi)
CODE_CUR = "INR"                  # redeem code ki currency
REDEEM_DISCOUNT = 10              # redeem code par discount %
SELLER_DEAL_ENABLED = True        # False = sirf admin NFT add kar sakta hai (/addnft)
BRAND = "@YourHandle"
PAY_INFO = (
    "UPI: zaid1012@fam"
    "TON: UQxxxxxxxxxxxxxxxx\n"
    "USDT (TRC20): Txxxxxxxxxxxxxxxx"
)
DB_FILE = os.getenv("DB_FILE", "deals.json")   # Railway: Volume lagao, DB_FILE=/data/deals.json
# ============================================

logging.basicConfig(level=logging.INFO)

# ---------- premium emojis (id, fallback) ----------
EMOJI = {
    "plane": ("5875465628285931233", "✈️"),
    "gift": ("6032937473162614352", "🎁"),
    "gift2": ("5875180111744995604", "🎁"),
    "pkg": ("5924720918826848520", "📦"),
    "tag": ("5870525453822859417", "🏷"),
    "user": ("5879770735999717115", "👤"),
    "user2": ("5771887475421090729", "👤"),
    "send": ("5877540355187937244", "📤"),
    "recv": ("5877307202888273539", "📥"),
    "star": ("5958376256788502078", "⭐️"),
    "spark": ("5931621672846103580", "💫"),
    "check": ("5825794181183836432", "✔️"),
    "link": ("5877465816030515018", "🔗"),
    "stat": ("5877485980901971030", "📊"),
    "sig": ("5874986954180791957", "📶"),
    "folder": ("5875206779196935950", "📁"),
    "trash": ("5879896690210639947", "🗑"),
    "gear": ("5877260593903177342", "⚙"),
    "search": ("5874960879434338403", "🔎"),
    "bot": ("5931415565955503486", "🤖"),
    "fire": ("6008118472066732010", "🔥"),
    "order": ("5843862283964390528", "🔖"),
    "people": ("5915556996215476302", "👥"),
    "arrow": ("5877468380125990242", "➡️"),
    "doc": ("5839323457015256759", "📄"),
    "pen": ("5879841310902324730", "✏️"),
}
DIV = "╍" * 14


def E(key):
    i, fb = EMOJI[key]
    return f'<tg-emoji emoji-id="{i}">{fb}</tg-emoji>'


esc = html.escape


# ---------- storage (restart par data safe) ----------
def load():
    db = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                db = json.load(f)
        except (ValueError, OSError):
            logging.exception("DB file read failed: %s", DB_FILE)
            try:
                os.replace(DB_FILE, DB_FILE + ".corrupt")
            except OSError:
                pass
            db = {}
    db.setdefault("n", 300)          # NFT deal counter
    db.setdefault("cn", 0)           # redeem order counter
    db.setdefault("deals", {})
    db.setdefault("products", {})    # pid -> {title, price, cur, stock:[codes]}
    db.setdefault("orders", {})      # redeem orders
    db.setdefault("groups", {})      # gid -> {busy: deal_id|None}
    db.setdefault("state", {})       # user conversation steps (restart-safe)
    return db


def _write(db, path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, path)


def save(db):
    global DB_FILE
    try:
        _write(db, DB_FILE)
    except OSError:
        logging.exception("DB save failed at %s, falling back to deals.json", DB_FILE)
        DB_FILE = "deals.json"
        _write(db, DB_FILE)


class PState:
    """User ka step/draft file me save hota hai, isliye restart par bhi nahi jaata."""
    def __init__(self, uid):
        self.uid = str(uid)

    def get(self, k, default=None):
        return load()["state"].get(self.uid, {}).get(k, default)

    def __getitem__(self, k):
        return load()["state"].get(self.uid, {})[k]

    def __setitem__(self, k, v):
        db = load()
        db["state"].setdefault(self.uid, {})[k] = v
        save(db)

    def clear(self):
        db = load()
        db["state"].pop(self.uid, None)
        save(db)


# ---------- formatting ----------
def fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else str(round(x, 2))


def fee_of(amount, pct=None):
    return round(amount * (FEE_PERCENT if pct is None else pct) / 100, 2)


def redeem_pay(face):
    return round(face * (100 - REDEEM_DISCOUNT) / 100, 2)


def name_of(u):
    return esc(f"@{u.username}" if u.username else u.first_name)


def is_admin(uid):
    return uid in ADMIN_IDS


STATUS = {
    "open": "🟢 Open - buyer ka wait",
    "await_pay": "🟡 Buyer payment kar raha hai",
    "in_group": "🔵 Payment confirm - deal room me chal rahi hai",
    "release_req": "🟠 Buyer ne release maanga - admin dekh raha hai",
    "done": "✅ Deal complete",
    "dispute": "⚠️ Dispute - admin dekh raha hai",
    "refunded": "↩️ Refunded",
    "cancelled": "❌ Cancelled",
}


def card(d):
    buyer = d["buyer_name"] if d.get("buyer") else "—"
    fee_lines = ""
    if d["fee"] > 0:
        fee_lines = (
            f"{E('send')} <b>Fee:</b> {fmt(d['fee'])} {d['cur']}\n"
            f"{E('recv')} <b>Seller gets:</b> {fmt(d['amount'] - d['fee'])} {d['cur']}\n"
        )
    return (
        f"{E('gift')} <b>NFT DEAL</b>  <code>#{d['id']}</code>\n{DIV}\n"
        f"{E('pkg')} <b>NFT:</b> {esc(d['item'])}\n"
        f"{E('tag')} <b>Price:</b> <b>{fmt(d['amount'])} {d['cur']}</b>\n"
        f"{fee_lines}{DIV}\n"
        f"{E('user')} <b>Seller:</b> {d['seller_name']}\n"
        f"{E('user2')} <b>Buyer:</b> {buyer}\n"
        f"{E('sig')} <b>Status:</b> {STATUS[d['status']]}\n{DIV}\n"
        f"{E('star')} Provided by {BRAND}"
    )


def pay_lines():
    out = []
    for ln in PAY_INFO.splitlines():
        if ": " in ln:
            k, v = ln.split(": ", 1)
            out.append(f"{esc(k)}: <code>{esc(v)}</code>")
        else:
            out.append(esc(ln))
    return "\n".join(out)


def pay_text(ref, amount, cur):
    return (
        f"{E('stat')} <b>PAYMENT DETAILS</b>\n{DIV}\n"
        f"{E('order')} <b>Order:</b> <code>{esc(ref)}</code>\n"
        f"{E('tag')} <b>Amount:</b> <b>{fmt(amount)} {cur}</b>\n{DIV}\n"
        f"{pay_lines()}\n{DIV}\n"
        f"{E('send')} Payment karke <b>screenshot isi chat me bhejo</b>.\n"
        f"{E('check')} Admin check karke confirm karega."
    )


def welcome(name):
    return (
        f"{E('plane')} <b>Welcome {name}!</b>\n{DIV}\n"
        f"{E('gift')} <b>NFT &amp; Redeem Code Bot</b>\n"
        f"{E('spark')} Provided by {BRAND}\n{DIV}\n"
        f"{E('star')} Telegram NFT aur Redeem Code safe tareeke se buy/sell karo\n\n"
        f"{E('search')} /nft - available NFT dekho\n"
        f"{E('send')} /sell - apna NFT sell karo\n"
        f"{E('gift2')} /buy - NFT buy karo\n"
        f"{E('folder')} /mydeals - meri deals aur orders\n"
        f"{E('gift2')} /redeemcode - redeem code lo\n{DIV}\n"
        f"{E('arrow')} Neeche ke buttons se bhi shuru kar sakte ho"
    )


def menu_kb():
    return M([
        [B("🎁 NFT List", callback_data="menu:nft"), B("💸 Sell NFT", callback_data="menu:sell")],
        [B("🎟 Redeem Code", callback_data="menu:redeem"), B("📋 My Deals", callback_data="menu:deals")],
    ])


# ---------- helpers ----------
async def notify(ctx, uid, text, kb=None):
    try:
        await ctx.bot.send_message(uid, text, reply_markup=kb)
        return True
    except Exception:
        return False  # user ne bot ko /start nahi kiya ho sakta hai


async def notify_admins(ctx, text, kb=None):
    for a in ADMIN_IDS:
        await notify(ctx, a, text, kb)


async def refresh(ctx, d, kb=None):
    try:
        await ctx.bot.edit_message_text(
            card(d), chat_id=d["chat"], message_id=d["mid"], reply_markup=kb)
    except Exception:
        pass


async def mark(q, text):
    try:
        await q.edit_message_text(text)
    except Exception:
        pass


async def need_admin(update):
    uid = update.effective_user.id
    if is_admin(uid):
        return True
    await update.effective_message.reply_text(
        f"⛔ <b>Ye command sirf admin ke liye hai.</b>\nAapka ID: <code>{uid}</code>\n"
        "Admin banna hai toh ye ID file me <code>ADMIN_IDS</code> list me daalo.")
    return False


async def post_card(ctx, d, here_chat):
    """Deal card post karta hai. GROUP_ID me fail ho toh isi chat me post kar deta hai."""
    kb = M([[B("🛒 Buy Now", callback_data=f"buy:{d['id']}")]])
    target = GROUP_ID or here_chat
    note = None
    try:
        m = await ctx.bot.send_message(target, card(d), reply_markup=kb)
    except Exception as e:
        if target == here_chat:
            raise
        m = await ctx.bot.send_message(here_chat, card(d), reply_markup=kb)
        note = (f"⚠️ GROUP_ID (<code>{target}</code>) me post nahi ho paya: {esc(str(e))}\n"
                "Bot ko us group me add + admin karo ya GROUP_ID sahi karo. Abhi yahin post kiya.")
    d["chat"], d["mid"] = m.chat_id, m.message_id
    return note


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error
    logging.error("Handler error", exc_info=err)
    if not isinstance(update, Update):
        return  # polling/network errors: sirf log
    msg = f"⚠️ Error: {type(err).__name__}: {err}"[:300]
    try:
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(esc(msg))
    except Exception:
        pass
    await notify_admins(ctx, esc(msg))


def pick_group(db):
    for g, v in db["groups"].items():
        if v["busy"] is None:
            return int(g)
    return None


def free_group(ctx, d):
    """60 sec baad dono ko group se nikaal ke group ko free kar deta hai."""
    gid = d.get("group")
    if not gid:
        return

    async def job():
        await asyncio.sleep(60)
        for uid in (d["seller"], d.get("buyer")):
            if not uid:
                continue
            try:
                await ctx.bot.ban_chat_member(gid, uid)
                await ctx.bot.unban_chat_member(gid, uid, only_if_banned=True)
            except Exception:
                pass
        for link in d.get("links", []):
            try:
                await ctx.bot.revoke_chat_invite_link(gid, link)
            except Exception:
                pass
        db2 = load()
        if str(gid) in db2["groups"]:
            db2["groups"][str(gid)]["busy"] = None
            save(db2)

    asyncio.create_task(job())


# ---------- basic commands ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        welcome(esc(update.effective_user.first_name)), reply_markup=menu_kb())


async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"{E('user')} <b>Your ID:</b> <code>{update.effective_user.id}</code>")


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/status - bot ki sehat check."""
    uid = update.effective_user.id
    db = load()
    try:
        save(db)
        saved = "OK"
    except Exception as e:
        saved = f"FAIL ({e})"
    open_n = sum(1 for d in db["deals"].values() if d["status"] == "open")
    await update.effective_message.reply_text(
        f"{E('gear')} <b>BOT STATUS</b>\n{DIV}\n"
        f"Aapka ID: <code>{uid}</code>\n"
        f"Admin: {'YES ✅' if is_admin(uid) else 'NO ❌ (ADMIN_IDS me ID daalo)'}\n"
        f"DB file: <code>{esc(DB_FILE)}</code> (write: {esc(saved)})\n"
        f"GROUP_ID: <code>{GROUP_ID}</code>\n"
        f"SELLER_DEAL_ENABLED: <code>{SELLER_DEAL_ENABLED}</code>\n"
        f"Open NFT: {open_n} | Deal groups: {len(db['groups'])}")


async def mydeals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load()
    out = []
    for d in db["deals"].values():
        if uid in (d["seller"], d.get("buyer")):
            out.append(f"{E('pkg')} <code>#{d['id']}</code> {esc(d['item'][:22])} - "
                       f"<b>{fmt(d['amount'])} {d['cur']}</b>\n      {STATUS[d['status']]}")
    for o in db["orders"].values():
        if o["uid"] == uid:
            out.append(f"{E('gift2')} <code>{o['id']}</code> {fmt(o['price'])} ka code - "
                       f"<b>{fmt(o.get('pay', o['price']))} {o['cur']}</b>\n      {esc(o['status'])}")
    if not out:
        await update.effective_message.reply_text(f"{E('folder')} Koi deal ya order nahi mila.")
        return
    await update.effective_message.reply_text(
        f"{E('folder')} <b>MY DEALS</b>\n{DIV}\n" + "\n\n".join(out[-12:]))


async def nft_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/nft aur /buy: available NFTs, har ek ke saath Buy button."""
    db = load()
    rows = [d for d in db["deals"].values() if d["status"] == "open"][-20:]
    if not rows:
        await update.effective_message.reply_text(f"{E('search')} Abhi koi NFT available nahi hai.")
        return
    text = f"{E('gift')} <b>AVAILABLE NFTs</b>\n{DIV}\n" + "\n".join(
        f"{E('pkg')} <code>#{d['id']}</code> {esc(d['item'][:35])} - <b>{fmt(d['amount'])} {d['cur']}</b>"
        for d in rows) + f"\n{DIV}\n{E('arrow')} Kharidne ke liye neeche Buy dabao"
    kb = M([[B(f"🛒 Buy #{d['id']} - {fmt(d['amount'])} {d['cur']}", callback_data=f"buy:{d['id']}")]
            for d in rows])
    await update.effective_message.reply_text(text, reply_markup=kb)


# ---------- NFT deal creation (seller) ----------
async def deal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Deal banane ke liye bot ko private chat me /sell bhejo.")
        return
    if not SELLER_DEAL_ENABLED and not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            f"{E('search')} Abhi sirf admin NFT list kar sakta hai. Kharidne ke liye /nft dekho.")
        return
    st = PState(update.effective_user.id)
    st.clear()
    st["step"] = "item"
    await update.effective_message.reply_text(
        f"{E('pkg')} <b>NFT SELL - Step 1/3</b>\n{DIV}\n"
        "NFT ka <b>naam ya link</b> bhejo\n"
        "<i>Example: t.me/nft/PlushPepe-1234 ya @username</i>")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    st = PState(user.id)
    step = st.get("step")
    if update.effective_chat.type != "private" or not step:
        return
    text = update.message.text.strip()

    if step == "item":
        st["item"] = text
        st["step"] = "amount"
        await update.message.reply_text(
            f"{E('tag')} <b>NFT SELL - Step 2/3</b>\n{DIV}\n"
            "<b>Price</b> bhejo (sirf number)\n<i>Example: 50</i>")

    elif step == "amount":
        try:
            amt = float(text)
            if amt <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Sahi number bhejo, jaise <code>50</code>")
            return
        st["amount"] = amt
        st["step"] = "cur"
        await update.message.reply_text(
            f"{E('stat')} <b>NFT SELL - Step 3/3</b>\n{DIV}\nCurrency select karo:",
            reply_markup=M([[B("💎 TON", callback_data="cur:TON"),
                             B("💵 USDT", callback_data="cur:USDT"),
                             B("🇮🇳 INR", callback_data="cur:INR")]]))

    elif step == "code_amount":
        try:
            amt = float(text)
            if amt <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Sahi amount likho, jaise <code>200</code>")
            return
        db = load()
        pid = next((k for k, v in db["products"].items() if v["price"] == amt and v["stock"]), None)
        p = db["products"][pid] if pid else None
        code = p["stock"].pop(0) if p else None
        title = p["title"] if p else "Redeem Code"
        cur = p["cur"] if p else CODE_CUR
        pay = redeem_pay(amt)
        db["cn"] += 1
        oid = f"RC{db['cn']}"
        db["orders"][oid] = {
            "id": oid, "uid": user.id, "uname": name_of(user), "pid": pid, "title": title,
            "price": amt, "pay": pay, "cur": cur, "code": code, "status": "await_pay",
            "time": int(time.time()),
        }
        save(db)
        st.clear()
        await update.message.reply_text(
            f"{E('gift2')} <b>REDEEM CODE</b>\n{DIV}\n"
            f"{E('tag')} <b>Code value:</b> <s>{fmt(amt)} {cur}</s>\n"
            f"{E('fire')} <b>{REDEEM_DISCOUNT}% discount</b> laga diya\n"
            f"{E('recv')} <b>Aapko dena hai:</b> <b>{fmt(pay)} {cur}</b>\n{DIV}\n"
            + pay_text(oid, pay, cur))
        how = ("Code stock me hai, confirm par auto-deliver hoga." if code else
               "Code stock me nahi hai, confirm ke baad /sendcode se bhejna padega.")
        await notify_admins(
            ctx, f"{E('gift2')} <b>Redeem order</b> <code>{oid}</code>\n{DIV}\n"
                 f"{E('tag')} {fmt(amt)} ka code | Pay: <b>{fmt(pay)} {cur}</b> ({REDEEM_DISCOUNT}% discount)\n"
                 f"{E('user')} Buyer: {name_of(user)}\n{esc(how)}",
            M([[B("✅ Payment mil gaya", callback_data=f"cpaid:{oid}"),
                B("❌ Cancel", callback_data=f"ccancel:{oid}")]]))


# ---------- payment screenshot -> admins ----------
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    db = load()
    refs = [f"NFT #{d['id']}" for d in db["deals"].values()
            if d.get("buyer") == uid and d["status"] == "await_pay"]
    refs += [f"CODE {o['id']}" for o in db["orders"].values()
             if o["uid"] == uid and o["status"] == "await_pay"]
    if not refs:
        return
    for a in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                a, f"{E('doc')} <b>Payment proof</b>\n{E('user')} {name_of(update.effective_user)} "
                   f"-> <code>{esc(', '.join(refs))}</code>")
            await update.message.copy(chat_id=a)
        except Exception:
            pass
    await update.message.reply_text(
        f"{E('check')} <b>Screenshot admin ko bhej diya.</b>\nConfirm hone ka wait karo.")


# ---------- admin: groups ----------
async def addgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(
            "Ye command us group me chalao jo deal group banana hai (bot ko admin banake).")
        return
    db = load()
    db["groups"].setdefault(str(chat.id), {"busy": None})
    save(db)
    await update.effective_message.reply_text(f"{E('check')} Ye group deal rooms ki list me add ho gaya.")


async def groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    if not db["groups"]:
        await update.effective_message.reply_text(
            "Koi deal group nahi. Group banao, bot ko admin banao, aur group me /addgroup chalao.")
        return
    await update.effective_message.reply_text(
        f"{E('people')} <b>DEAL ROOMS</b>\n{DIV}\n" + "\n".join(
            f"<code>{g}</code> -> {'🟢 FREE' if v['busy'] is None else '🔴 BUSY (deal #' + str(v['busy']) + ')'}"
            for g, v in db["groups"].items()))


# ---------- admin: NFT add / list / delete ----------
async def addnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addnft Item | price | TON   (currency optional, default TON)"""
    user = update.effective_user
    if not await need_admin(update):
        return
    msg = update.effective_message
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "|" not in parts[1]:
        await msg.reply_text(
            f"{E('pen')} <b>Format:</b>\n<code>/addnft Item | price | TON</code>\n\n<b>Example:</b>\n"
            "<code>/addnft t.me/nft/PlushPepe-1234 | 50 | TON</code>\n"
            "<code>/addnft @coolusername | 1500 | INR</code>")
        return
    bits = [p.strip() for p in parts[1].split("|")]
    item = bits[0]
    try:
        amt = float(bits[1])
        if amt <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await msg.reply_text("❌ Price number hona chahiye, jaise <code>50</code>")
        return
    cur = (bits[2].upper() if len(bits) > 2 and bits[2] else "TON")
    if cur not in ("TON", "USDT", "INR"):
        await msg.reply_text("❌ Currency TON, USDT ya INR hi ho sakti hai.")
        return
    db = load()
    db["n"] += 1
    did = str(db["n"])
    d = {
        "id": did, "item": item, "amount": amt, "cur": cur,
        "fee": fee_of(amt, ADMIN_FEE), "seller": user.id, "seller_name": name_of(user),
        "buyer": None, "buyer_name": None, "status": "open", "time": int(time.time()),
        "by_admin": True,
    }
    note = await post_card(ctx, d, update.effective_chat.id)
    db["deals"][did] = d
    save(db)
    if note:
        await msg.reply_text(note)
    elif GROUP_ID and GROUP_ID != update.effective_chat.id:
        await msg.reply_text(f"{E('check')} NFT <code>#{did}</code> list ho gaya.")


async def nfts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    rows = [d for d in db["deals"].values() if d["status"] == "open"]
    if not rows:
        await update.effective_message.reply_text("Koi open NFT nahi hai.")
        return
    await update.effective_message.reply_text(
        f"{E('gift')} <b>OPEN NFTs</b>\n{DIV}\n" + "\n".join(
            f"<code>#{d['id']}</code> {esc(d['item'][:30])} - {fmt(d['amount'])} {d['cur']} - {d['seller_name']}"
            for d in rows[-30:]))


async def delnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Deal ID do, jaise <code>/delnft 301</code>")
        return
    db = load()
    d = db["deals"].get(ctx.args[0].replace("#", ""))
    if not d:
        await update.effective_message.reply_text("Deal nahi mili.")
        return
    if d["status"] != "open":
        await update.effective_message.reply_text(
            "Sirf open NFT hata sakte ho. Chalu deal ke liye /cancel ya /refund use karo.")
        return
    d["status"] = "cancelled"
    save(db)
    await refresh(ctx, d)
    await update.effective_message.reply_text(f"{E('trash')} NFT <code>#{d['id']}</code> hata diya.")


# ---------- admin: refund / cancel NFT deal ----------
async def admin_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE, new_status, msg):
    if not await need_admin(update):
        return
    if not ctx.args:
        await update.effective_message.reply_text("Deal ID do, jaise <code>/refund 301</code>")
        return
    db = load()
    d = db["deals"].get(ctx.args[0].replace("#", ""))
    if not d:
        await update.effective_message.reply_text("Deal nahi mili.")
        return
    d["status"] = new_status
    save(db)
    await refresh(ctx, d)
    await notify(ctx, d["seller"], f"{E('gift')} <code>#{d['id']}</code>: {esc(msg)}")
    if d.get("buyer"):
        await notify(ctx, d["buyer"], f"{E('gift')} <code>#{d['id']}</code>: {esc(msg)}")
    free_group(ctx, d)
    await update.effective_message.reply_text(f"<code>#{d['id']}</code> -> {new_status}")


async def refund(update, ctx):
    await admin_set(update, ctx, "refunded", "Payment buyer ko refund ho gaya.")


async def cancel(update, ctx):
    await admin_set(update, ctx, "cancelled", "Deal cancel kar di gayi.")


# ---------- redeem codes ----------
async def codes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/redeemcode: pehle puchta hai kitne ka chahiye."""
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text(
            "Redeem code lene ke liye bot ko private chat me /redeemcode bhejo.")
        return
    st = PState(update.effective_user.id)
    st.clear()
    st["step"] = "code_amount"
    await update.effective_message.reply_text(
        f"{E('gift2')} <b>REDEEM CODE</b>\n{DIV}\n"
        "<b>Kitne ka redeem code chahiye aapko?</b>\n"
        "Amount likho <i>(jaise 200)</i>\n\n"
        f"{E('fire')} <b>{REDEEM_DISCOUNT}% discount</b> milega!")


async def addcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addcode 200 | CODE1, CODE2   ya   /addcode Google Play | 200 | CODE1, CODE2"""
    if not await need_admin(update):
        return
    parts = update.effective_message.text.split(maxsplit=1)
    bits = [b.strip() for b in parts[1].split("|", 2)] if len(parts) > 1 else []
    if len(bits) == 2:
        title, value, codes_txt = "Redeem Code", bits[0], bits[1]
    elif len(bits) == 3:
        title, value, codes_txt = bits
    else:
        await update.effective_message.reply_text(
            f"{E('pen')} <b>Format:</b>\n<code>/addcode 200 | CODE1, CODE2</code>\nya\n"
            "<code>/addcode Google Play | 200 | CODE1, CODE2</code>")
        return
    try:
        value = float(value)
    except ValueError:
        await update.effective_message.reply_text("❌ Value number hona chahiye, jaise <code>200</code>")
        return
    new = [c.strip() for c in codes_txt.replace("\n", ",").split(",") if c.strip()]
    if not new:
        await update.effective_message.reply_text("Koi code nahi mila.")
        return
    db = load()
    pid = next((k for k, v in db["products"].items()
                if v["title"].lower() == title.lower() and v["price"] == value), None)
    if pid is None:
        pid = str(max([int(k) for k in db["products"]] + [0]) + 1)
        db["products"][pid] = {"title": title, "price": value, "cur": CODE_CUR, "stock": []}
    db["products"][pid]["stock"].extend(new)
    save(db)
    await update.effective_message.reply_text(
        f"{E('check')} <b>{esc(title)}</b> {fmt(value)} ka: {len(new)} code add.\n"
        f"Total stock: {len(db['products'][pid]['stock'])}")


async def stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    if not db["products"]:
        await update.effective_message.reply_text("Koi redeem code stock nahi.")
        return
    await update.effective_message.reply_text(
        f"{E('stat')} <b>REDEEM STOCK</b>\n{DIV}\n" + "\n".join(
            f"{esc(v['title'])} | {fmt(v['price'])} ka | user pay {fmt(redeem_pay(v['price']))} {v['cur']}"
            f" | stock <b>{len(v['stock'])}</b>" for v in db["products"].values()))


async def sendcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/sendcode RC5 CODE - stock me code nahi tha toh payment ke baad admin code bhejta hai."""
    if not await need_admin(update):
        return
    parts = update.effective_message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.effective_message.reply_text("Format: <code>/sendcode RC5 CODE</code>")
        return
    db = load()
    o = db["orders"].get(parts[1].upper())
    if not o or o["status"] != "paid":
        await update.effective_message.reply_text("Order nahi mila ya uska payment confirm nahi hai.")
        return
    code = parts[2].strip()
    ok = await notify(
        ctx, o["uid"],
        f"{E('gift2')} <b>ORDER DELIVERED</b> <code>{o['id']}</code>\n{DIV}\n"
        f"{E('tag')} <b>{fmt(o['price'])} ka redeem code:</b>\n<code>{esc(code)}</code>\n{DIV}\n"
        f"{E('star')} Thanks for buying from {BRAND}")
    if not ok:
        await update.effective_message.reply_text("Buyer ko DM nahi gaya (bot block/start nahi).")
        return
    o["status"], o["code"] = "done", code
    save(db)
    await update.effective_message.reply_text(
        f"{E('check')} Order <code>{o['id']}</code> deliver ho gaya ({o['uname']}).")


# ---------- buttons ----------
async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    uid = user.id
    act, _, arg = q.data.partition(":")

    # ===== start menu buttons =====
    if act == "menu":
        await q.answer()
        fn = {"nft": nft_list, "sell": deal, "redeem": codes, "deals": mydeals}.get(arg)
        if fn:
            await fn(update, ctx)
        return

    db = load()

    # ===== NFT deal create (seller picks currency) =====
    if act == "cur":
        if PState(uid).get("step") != "cur":
            await q.answer("Dubara /sell karo", show_alert=True)
            return
        db["n"] += 1
        did = str(db["n"])
        amt = PState(uid)["amount"]
        d = {
            "id": did, "item": PState(uid)["item"], "amount": amt, "cur": arg,
            "fee": fee_of(amt), "seller": uid, "seller_name": name_of(user),
            "buyer": None, "buyer_name": None, "status": "open", "time": int(time.time()),
        }
        note = await post_card(ctx, d, q.message.chat_id)
        db["deals"][did] = d
        save(db)
        PState(uid).clear()
        if note:
            await ctx.bot.send_message(q.message.chat_id, note)
        await q.answer("Deal ban gayi")
        await q.edit_message_text(
            f"{E('check')} <b>Deal</b> <code>#{did}</code> <b>ban gayi aur post ho gayi!</b>\n"
            "Buyer aate hi aapko bata diya jayega.")
        return

    # ===== redeem order: admin actions =====
    if act in ("cpaid", "ccancel"):
        o = db["orders"].get(arg)
        if not is_admin(uid) or not o or o["status"] != "await_pay":
            await q.answer("Not allowed", show_alert=True)
            return
        if act == "cpaid" and not o["code"]:
            o["status"] = "paid"
            save(db)
            await notify(ctx, o["uid"],
                         f"{E('check')} <b>Order</b> <code>{o['id']}</code>: payment confirm ho gaya.\n"
                         "Aapka redeem code thodi der me mil jayega.")
            await mark(q, f"{E('check')} Order <code>{o['id']}</code> payment confirm.\n"
                          f"Ab {o['uname']} ko {fmt(o['price'])} ka code bhejo:\n"
                          f"<code>/sendcode {o['id']} CODE</code>")
        elif act == "cpaid":
            ok = await notify(
                ctx, o["uid"],
                f"{E('gift2')} <b>ORDER DELIVERED</b> <code>{o['id']}</code>\n{DIV}\n"
                f"{E('tag')} <b>{fmt(o['price'])} ka redeem code:</b>\n<code>{esc(o['code'])}</code>\n{DIV}\n"
                f"{E('star')} Thanks for buying from {BRAND}")
            if not ok:
                await q.answer("Buyer ko DM nahi gaya (bot block/start nahi)", show_alert=True)
                return
            o["status"] = "done"
            save(db)
            await mark(q, f"{E('check')} Order <code>{o['id']}</code> delivered to {o['uname']}")
        else:
            o["status"] = "cancelled"
            if o["code"] and o["pid"]:
                db["products"][o["pid"]]["stock"].insert(0, o["code"])
            save(db)
            await notify(ctx, o["uid"], f"❌ Order <code>{o['id']}</code> cancel ho gaya.")
            await mark(q, f"❌ Order <code>{o['id']}</code> cancelled, code wapas stock me")
        await q.answer("Done")
        return

    # ===== NFT deal actions =====
    d = db["deals"].get(arg)
    if not d:
        await q.answer("Deal nahi mili", show_alert=True)
        return

    if act == "buy":
        if d["status"] != "open":
            await q.answer("Ye deal ab open nahi hai", show_alert=True)
            return
        if uid == d["seller"]:
            await q.answer("Apni hi deal nahi khareed sakte", show_alert=True)
            return
        ok = await notify(ctx, uid, pay_text(f"NFT #{d['id']}", d["amount"], d["cur"]))
        if not ok:
            await q.answer("Pehle bot ko private me /start karo, phir dobara Buy dabao", show_alert=True)
            return
        d["buyer"], d["buyer_name"], d["status"] = uid, name_of(user), "await_pay"
        save(db)
        await q.answer("Payment details DM me bhej di")
        await refresh(ctx, d)
        await notify(ctx, d["seller"],
                     f"{E('user2')} <code>#{d['id']}</code>: {d['buyer_name']} ne buy kiya.\n"
                     "Payment confirm hone ka wait karo.")
        await notify_admins(
            ctx, f"{E('stat')} <b>NFT</b> <code>#{d['id']}</code> - {esc(d['item'])}\n{DIV}\n"
                 f"{E('user2')} Buyer: {d['buyer_name']}\n{E('user')} Seller: {d['seller_name']}\n"
                 f"{E('tag')} Amount: <b>{fmt(d['amount'])} {d['cur']}</b>\n{DIV}\n"
                 "Payment aaye toh confirm karo:",
            M([[B("✅ Payment mil gaya", callback_data=f"paid:{d['id']}")]]))

    elif act == "paid":
        if not is_admin(uid) or d["status"] != "await_pay":
            await q.answer("Not allowed", show_alert=True)
            return
        gid = pick_group(db)
        if gid is None:
            await q.answer("Koi free deal group nahi! Naya group banao, bot ko admin banao aur /addgroup chalao.",
                           show_alert=True)
            return
        try:
            exp = int(time.time()) + 86400
            l1 = await ctx.bot.create_chat_invite_link(gid, member_limit=1, expire_date=exp)
            l2 = await ctx.bot.create_chat_invite_link(gid, member_limit=1, expire_date=exp)
        except Exception:
            await q.answer("Invite link nahi bana. Bot ko us group me admin banao (Invite Users right).",
                           show_alert=True)
            return
        d["status"], d["group"] = "in_group", gid
        d["links"] = [l1.invite_link, l2.invite_link]
        db["groups"][str(gid)]["busy"] = d["id"]
        save(db)
        await q.answer("Confirmed")
        await mark(q, f"{E('check')} NFT <code>#{d['id']}</code> payment confirm, group links bhej diye.")
        await refresh(ctx, d)

        try:
            await ctx.bot.send_message(
                gid,
                f"{E('people')} <b>DEAL ROOM</b>  <code>#{d['id']}</code>\n{DIV}\n"
                f"{E('pkg')} <b>NFT:</b> {esc(d['item'])}\n"
                f"{E('tag')} <b>Price:</b> <b>{fmt(d['amount'])} {d['cur']}</b>\n"
                f"{E('user')} <b>Seller:</b> {d['seller_name']}\n"
                f"{E('user2')} <b>Buyer:</b> {d['buyer_name']}\n{DIV}\n"
                f"{E('check')} Payment verify ho chuka hai. Dono yahin deal complete karo.\n"
                "⚠️ NFT mil jaane ke baad sirf <b>BUYER</b> neeche button dabaye.",
                reply_markup=M([[B("✅ NFT mil gaya - Payment release karo", callback_data=f"rel:{d['id']}")],
                                [B("⚠️ Problem / Dispute", callback_data=f"dispute:{d['id']}")]]))
        except Exception:
            pass

        for who, target, link in (("Buyer", d["buyer"], l1.invite_link), ("Seller", d["seller"], l2.invite_link)):
            text = (f"{E('check')} <b>Deal</b> <code>#{d['id']}</code>: payment confirm ho gaya!\n{DIV}\n"
                    f"{E('link')} Deal room join karo <i>(1 baar chalne wala link)</i>:\n{esc(link)}")
            if not await notify(ctx, target, text):
                await notify_admins(
                    ctx, f"⚠️ {who} ko DM nahi gaya (deal <code>#{d['id']}</code>). Ye link manually bhejo:\n{esc(link)}")

    elif act == "rel":
        if uid != d["buyer"] or d["status"] != "in_group":
            await q.answer("Sirf buyer ye button dabaa sakta hai", show_alert=True)
            return
        d["status"] = "release_req"
        save(db)
        await q.answer("Admin ko release request bhej di")
        await refresh(ctx, d)
        await mark(q, f"🟠 Deal <code>#{d['id']}</code>: buyer ne payment release maanga hai.\n"
                      "Admin process kar raha hai.")
        await notify_admins(
            ctx, f"{E('check')} <b>Deal</b> <code>#{d['id']}</code>: buyer ne NFT confirm kiya.\n{DIV}\n"
                 f"{E('send')} Seller {d['seller_name']} ko <b>{fmt(d['amount'] - d['fee'])} {d['cur']}</b> "
                 "release karo, phir button dabao:",
            M([[B("📤 Released (done)", callback_data=f"release:{d['id']}")]]))

    elif act == "release":
        if not is_admin(uid) or d["status"] != "release_req":
            await q.answer("Not allowed", show_alert=True)
            return
        d["status"] = "done"
        save(db)
        await q.answer("Done")
        await mark(q, f"{E('check')} Deal <code>#{d['id']}</code> complete.")
        await refresh(ctx, d)
        await notify(ctx, d["seller"],
                     f"{E('fire')} <b>Deal</b> <code>#{d['id']}</code> <b>complete!</b>\n"
                     f"{E('recv')} {fmt(d['amount'] - d['fee'])} {d['cur']} release ho gaye.")
        await notify(ctx, d["buyer"],
                     f"{E('fire')} <b>Deal</b> <code>#{d['id']}</code> <b>complete!</b>\n"
                     f"{E('star')} Thanks for using {BRAND}")
        try:
            await ctx.bot.send_message(
                d["group"], f"{E('fire')} <b>Deal</b> <code>#{d['id']}</code> <b>complete!</b>\n"
                            "Ye room 60 sec me khaali ho jayega.")
        except Exception:
            pass
        free_group(ctx, d)

    elif act == "dispute":
        if uid not in (d["seller"], d.get("buyer")) or d["status"] not in ("await_pay", "in_group", "release_req"):
            await q.answer("Not allowed", show_alert=True)
            return
        d["status"] = "dispute"
        save(db)
        await q.answer("Admin ko bata diya")
        await refresh(ctx, d)
        await notify_admins(
            ctx, f"⚠️ <b>DISPUTE</b> <code>#{d['id']}</code>\n{DIV}\n"
                 f"{E('user')} Seller: {d['seller_name']}\n{E('user2')} Buyer: {d['buyer_name']}\n"
                 f"Raised by: {name_of(user)}\n{DIV}\n"
                 f"<code>/refund {d['id']}</code>  ya  <code>/cancel {d['id']}</code>")


async def post_init(app):
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Menu kholo"),
            BotCommand("nft", "Available NFT dekho"),
            BotCommand("sell", "Apna NFT sell karo"),
            BotCommand("buy", "NFT buy karo"),
            BotCommand("mydeals", "Meri deals aur orders"),
            BotCommand("redeemcode", "Redeem code lo"),
        ])
    except Exception:
        logging.exception("set_my_commands failed")


def main():
    app = (Application.builder().token(TOKEN)
           .defaults(Defaults(parse_mode=ParseMode.HTML))
           .post_init(post_init).build())
    for name, fn in (
        ("start", start), ("myid", myid), ("status", status), ("mydeals", mydeals),
        ("nft", nft_list), ("buy", nft_list), ("sell", deal), ("deal", deal),
        ("redeemcode", codes), ("codes", codes), ("addcode", addcode), ("stock", stock),
        ("sendcode", sendcode), ("addgroup", addgroup), ("groups", groups),
        ("addnft", addnft), ("nfts", nfts), ("delnft", delnft),
        ("refund", refund), ("cancel", cancel),
    ):
        app.add_handler(CommandHandler(name, fn))
    app.add_error_handler(on_error)
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
