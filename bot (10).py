import asyncio
import json
import logging
import os
import time

from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# ================= SETTINGS =================
TOKEN = os.getenv("BOT_TOKEN", "PASTE_BOT_TOKEN_HERE")
ADMIN_IDS = [7054168366]          # admins (aur IDs yahan add karo)
GROUP_ID = None                   # deal cards kis group me post hon (e.g. -100123...), None = same chat
FEE_PERCENT = 3                   # NFT deal fee in %
CODE_CUR = "INR"                  # redeem code ki currency
SELLER_DEAL_ENABLED = True        # False = sirf admin NFT add kar sakta hai (/addnft), users ka /deal band
REDEEM_DISCOUNT = 10              # redeem code par user ko discount %
ADMIN_FEE = 0                     # admin ke add kiye NFT par fee % (0 = koi fee nahi)
BRAND = "@YourHandle"
PAY_INFO = (
    "UPI: yourupi@bank\n"
    "TON: UQxxxxxxxxxxxxxxxx\n"
    "USDT (TRC20): Txxxxxxxxxxxxxxxx"
)
DB_FILE = os.getenv("DB_FILE", "deals.json")   # Railway: Volume lagao, DB_FILE=/data/deals.json
# ============================================

logging.basicConfig(level=logging.INFO)


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
    db.setdefault("n", 300)          # deal counter
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
        # Volume nahi laga / folder read-only: local file par chalte raho
        logging.exception("DB save failed at %s, falling back to deals.json", DB_FILE)
        DB_FILE = "deals.json"
        _write(db, DB_FILE)


# ---------- helpers ----------

class PState:
    """User ka step/draft file me save hota hai, isliye bot restart par bhi nahi jaata."""
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

STATUS = {
    "open": "🟢 Open (buyer ka wait)",
    "await_pay": "🟡 Buyer payment kar raha hai",
    "in_group": "🔵 Payment confirm, deal group me chal rahi hai",
    "release_req": "🟠 Buyer ne release maanga, admin dekh raha hai",
    "done": "✅ Deal complete",
    "dispute": "⚠️ Dispute (admin dekh raha hai)",
    "refunded": "↩️ Refunded",
    "cancelled": "❌ Cancelled",
}


def fee_of(amount):
    return round(amount * FEE_PERCENT / 100, 2)


def card(d):
    buyer = d["buyer_name"] if d.get("buyer") else "—"
    fee_lines = ""
    if d["fee"] > 0:
        fee_lines = (
            f"💸 Fee: {d['fee']} {d['cur']}\n"
            f"📤 Seller gets: {round(d['amount'] - d['fee'], 2)} {d['cur']}\n"
        )
    return (
        f"🎁 NFT DEAL  #{d['id']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🖼 NFT: {d['item']}\n"
        f"💰 Price: {d['amount']} {d['cur']}\n"
        f"{fee_lines}"
        f"━━━━━━━━━━━━━━\n"
        f"👤 Seller: {d['seller_name']}\n"
        f"🛒 Buyer: {buyer}\n"
        f"📌 Status: {STATUS[d['status']]}\n\n"
        f"Provided by {BRAND}"
    )


def pay_text(ref, amount, cur):
    return (
        f"💳 PAYMENT DETAILS\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 Order: {ref}\n"
        f"💰 Amount: {amount} {cur}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{PAY_INFO}\n"
        f"━━━━━━━━━━━━━━\n"
        f"Payment ke baad screenshot isi chat me bhejo.\n"
        f"Admin check karke confirm karega."
    )


def name_of(u):
    return f"@{u.username}" if u.username else u.first_name


def is_admin(uid):
    return uid in ADMIN_IDS


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
            card(d), chat_id=d["chat"], message_id=d["mid"], reply_markup=kb
        )
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
        f"⛔ Ye command sirf admin ke liye hai.\nAapka ID: {uid}\n"
        "Admin banna hai toh ye ID file me ADMIN_IDS list me daalo.")
    return False


async def post_card(ctx, d, here_chat):
    """Deal card post karta hai. GROUP_ID me fail ho toh isi chat me post kar deta hai."""
    kb = M([[B("🛒 Buy", callback_data=f"buy:{d['id']}")]])
    target = GROUP_ID or here_chat
    note = None
    try:
        m = await ctx.bot.send_message(target, card(d), reply_markup=kb)
    except Exception as e:
        if target == here_chat:
            raise
        m = await ctx.bot.send_message(here_chat, card(d), reply_markup=kb)
        note = (f"⚠️ GROUP_ID ({target}) me post nahi ho paya: {e}\n"
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
            await update.effective_message.reply_text(msg)
    except Exception:
        pass
    await notify_admins(ctx, msg)


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/status - bot ki sehat check (sabhi ke liye, ID dikhata hai)."""
    uid = update.effective_user.id
    db = load()
    try:
        save(db)
        saved = "OK"
    except Exception as e:
        saved = f"FAIL ({e})"
    open_n = sum(1 for d in db["deals"].values() if d["status"] == "open")
    await update.effective_message.reply_text(
        f"🩺 BOT STATUS\n"
        f"Aapka ID: {uid}\n"
        f"Admin: {'YES' if is_admin(uid) else 'NO (ADMIN_IDS me ID daalo)'}\n"
        f"DB file: {DB_FILE} (write: {saved})\n"
        f"GROUP_ID: {GROUP_ID}\n"
        f"SELLER_DEAL_ENABLED: {SELLER_DEAL_ENABLED}\n"
        f"Open NFT: {open_n} | Deal groups: {len(db['groups'])}")


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
    await update.message.reply_text(
        f"NFT & Redeem Code Bot\nProvided by {BRAND}\n\n"
        "/nft - isse pata chalega kaun kaun se NFT available hain\n"
        "/sell - isse apna NFT sell kar sakte ho\n"
        "/buy - isse NFT buy kar sakte ho\n"
        "/mydeals - meri deals aur orders\n"
        "/redeemcode - isse redeem code le sakte ho"
    )


async def nft_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/nft aur /buy: available NFTs ki list, har ek ke saath Buy button."""
    db = load()
    rows = [d for d in db["deals"].values() if d["status"] == "open"][-20:]
    if not rows:
        await update.message.reply_text("Abhi koi NFT available nahi hai.")
        return
    text = "🎁 AVAILABLE NFTs\n━━━━━━━━━━━━━━\n" + "\n".join(
        f"#{d['id']} | {d['item'][:35]} | {d['amount']} {d['cur']}" for d in rows)
    kb = M([[B(f"🛒 Buy #{d['id']} - {d['amount']} {d['cur']}", callback_data=f"buy:{d['id']}")] for d in rows])
    await update.message.reply_text(text, reply_markup=kb)


async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")


async def mydeals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load()
    out = []
    for d in db["deals"].values():
        if uid in (d["seller"], d.get("buyer")):
            out.append(f"NFT #{d['id']} | {d['item'][:22]} | {d['amount']} {d['cur']} | {STATUS[d['status']]}")
    for o in db["orders"].values():
        if o["uid"] == uid:
            out.append(f"CODE {o['id']} | {o['title'][:22]} | {fmt(o.get('pay', o['price']))} {o['cur']} | {o['status']}")
    await update.message.reply_text("\n".join(out[-20:]) if out else "Koi deal ya order nahi mila.")


# ---------- NFT deal creation (seller) ----------
async def deal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Deal banane ke liye bot ko private chat me /deal bhejo.")
        return
    if not SELLER_DEAL_ENABLED and not is_admin(update.effective_user.id):
        await update.message.reply_text("Abhi sirf admin NFT list kar sakta hai. Kharidne ke liye deal card par Buy dabao.")
        return
    PState(update.effective_user.id).clear()
    PState(update.effective_user.id)["step"] = "item"
    await update.message.reply_text("🖼 NFT ka naam ya link bhejo (gift link ya @username):")


# ---------- admin: NFT add / list / delete ----------
async def addnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addnft Item | price | TON   (currency optional, default TON)
    Card usi chat me post hota hai jahan command chalaya (ya GROUP_ID me)."""
    user = update.effective_user
    if not await need_admin(update):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2 or "|" not in parts[1]:
        await update.message.reply_text(
            "Format:\n/addnft Item | price | TON\n\nExample:\n"
            "/addnft t.me/nft/PlushPepe-1234 | 50 | TON\n"
            "/addnft @coolusername | 1500 | INR")
        return
    bits = [p.strip() for p in parts[1].split("|")]
    item = bits[0]
    try:
        amt = float(bits[1])
        if amt <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("Price number hona chahiye, jaise 50")
        return
    cur = (bits[2].upper() if len(bits) > 2 and bits[2] else "TON")
    if cur not in ("TON", "USDT", "INR"):
        await update.message.reply_text("Currency TON, USDT ya INR hi ho sakti hai.")
        return
    db = load()
    db["n"] += 1
    did = str(db["n"])
    d = {
        "id": did, "item": item, "amount": amt, "cur": cur,
        "fee": round(amt * ADMIN_FEE / 100, 2), "seller": user.id, "seller_name": name_of(user),
        "buyer": None, "buyer_name": None, "status": "open", "time": int(time.time()),
        "by_admin": True,
    }
    note = await post_card(ctx, d, update.effective_chat.id)
    db["deals"][did] = d
    save(db)
    if note:
        await update.effective_message.reply_text(note)
    elif GROUP_ID and GROUP_ID != update.effective_chat.id:
        await update.effective_message.reply_text(f"✅ NFT #{did} list ho gaya.")


async def nfts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    rows = [d for d in db["deals"].values() if d["status"] == "open"]
    if not rows:
        await update.message.reply_text("Koi open NFT nahi hai.")
        return
    await update.message.reply_text("\n".join(
        f"#{d['id']} | {d['item'][:30]} | {d['amount']} {d['cur']} | {d['seller_name']}" for d in rows[-30:]))


async def delnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Deal ID do, jaise /delnft 301")
        return
    db = load()
    d = db["deals"].get(ctx.args[0].replace("#", ""))
    if not d:
        await update.message.reply_text("Deal nahi mili.")
        return
    if d["status"] != "open":
        await update.message.reply_text("Sirf open NFT hata sakte ho. Chalu deal ke liye /cancel ya /refund use karo.")
        return
    d["status"] = "cancelled"
    save(db)
    await refresh(ctx, d)
    await update.message.reply_text(f"🗑 NFT #{d['id']} hata diya.")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = PState(update.effective_user.id).get("step")
    if update.effective_chat.type != "private" or not step:
        return
    text = update.message.text.strip()

    if step == "item":
        PState(update.effective_user.id)["item"] = text
        PState(update.effective_user.id)["step"] = "amount"
        await update.message.reply_text("💰 Price (sirf number) bhejo:")
    elif step == "code_amount":
        try:
            amt = float(text)
            if amt <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Sahi amount likho, jaise 200")
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
        user = update.effective_user
        db["orders"][oid] = {
            "id": oid, "uid": user.id, "uname": name_of(user), "pid": pid, "title": title,
            "price": amt, "pay": pay, "cur": cur, "code": code, "status": "await_pay",
            "time": int(time.time()),
        }
        save(db)
        PState(user.id).clear()
        await update.message.reply_text(
            f"🎟 {fmt(amt)} ka redeem code\n"
            f"🎁 {REDEEM_DISCOUNT}% discount ke baad total: {fmt(pay)} {cur}\n\n"
            + pay_text(oid, fmt(pay), cur))
        how = "Code stock me hai, confirm par auto-deliver hoga." if code else \
              "Code stock me nahi hai, confirm ke baad /sendcode se bhejna padega."
        await notify_admins(
            ctx, f"🎟 Redeem order {oid}\n{fmt(amt)} ka | Pay: {fmt(pay)} {cur} ({REDEEM_DISCOUNT}% discount)\n"
                 f"Buyer: {name_of(user)}\n{how}",
            M([[B("✅ Payment mil gaya", callback_data=f"cpaid:{oid}"),
                B("❌ Cancel", callback_data=f"ccancel:{oid}")]]))
    elif step == "amount":
        try:
            amt = float(text)
            if amt <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Sahi number bhejo, jaise 50")
            return
        PState(update.effective_user.id)["amount"] = amt
        PState(update.effective_user.id)["step"] = "cur"
        await update.message.reply_text(
            "Currency select karo:",
            reply_markup=M([[B("TON", callback_data="cur:TON"),
                             B("USDT", callback_data="cur:USDT"),
                             B("INR", callback_data="cur:INR")]]),
        )


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
            await ctx.bot.send_message(a, f"📸 Payment proof: {name_of(update.effective_user)} -> {', '.join(refs)}")
            await update.message.copy(chat_id=a)
        except Exception:
            pass
    await update.message.reply_text("✅ Screenshot admin ko bhej diya. Confirm hone ka wait karo.")


# ---------- admin: groups ----------
async def addgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Ye command us group me chalao jo deal group banana hai (bot ko admin banake).")
        return
    db = load()
    db["groups"].setdefault(str(chat.id), {"busy": None})
    save(db)
    await update.message.reply_text("✅ Ye group deal groups ki list me add ho gaya.")


async def groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    if not db["groups"]:
        await update.message.reply_text("Koi deal group nahi. Group banao, bot ko admin banao, aur group me /addgroup chalao.")
        return
    await update.message.reply_text("\n".join(
        f"{g} -> {'FREE' if v['busy'] is None else 'BUSY (deal #' + str(v['busy']) + ')'}"
        for g, v in db["groups"].items()))


# ---------- admin: refund / cancel NFT deal ----------
async def admin_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE, new_status, msg):
    if not await need_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Deal ID do, jaise /refund 301")
        return
    db = load()
    d = db["deals"].get(ctx.args[0].replace("#", ""))
    if not d:
        await update.message.reply_text("Deal nahi mili.")
        return
    d["status"] = new_status
    save(db)
    await refresh(ctx, d)
    await notify(ctx, d["seller"], f"#{d['id']}: {msg}")
    if d.get("buyer"):
        await notify(ctx, d["buyer"], f"#{d['id']}: {msg}")
    free_group(ctx, d)
    await update.message.reply_text(f"#{d['id']} -> {new_status}")


async def refund(update, ctx):
    await admin_set(update, ctx, "refunded", "Payment buyer ko refund ho gaya.")


async def cancel(update, ctx):
    await admin_set(update, ctx, "cancelled", "Deal cancel kar di gayi.")


# ---------- redeem codes ----------
def fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else str(x)


def redeem_pay(face):
    return round(face * (100 - REDEEM_DISCOUNT) / 100, 2)


def code_values(db):
    return sorted({v["price"] for v in db["products"].values() if v["stock"]})


async def addcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addcode 200 | CODE1, CODE2   ya   /addcode Google Play | 200 | CODE1, CODE2
    (200 = code ki face value; user ko REDEEM_DISCOUNT% kam me milega)"""
    if not await need_admin(update):
        return
    parts = update.message.text.split(maxsplit=1)
    bits = [b.strip() for b in parts[1].split("|", 2)] if len(parts) > 1 else []
    if len(bits) == 2:
        title, value, codes_txt = "Redeem Code", bits[0], bits[1]
    elif len(bits) == 3:
        title, value, codes_txt = bits
    else:
        await update.message.reply_text(
            "Format:\n/addcode 200 | CODE1, CODE2\nya\n/addcode Google Play | 200 | CODE1, CODE2")
        return
    try:
        value = float(value)
    except ValueError:
        await update.message.reply_text("Value number hona chahiye, jaise 200")
        return
    new = [c.strip() for c in codes_txt.replace("\n", ",").split(",") if c.strip()]
    if not new:
        await update.message.reply_text("Koi code nahi mila.")
        return
    db = load()
    pid = next((k for k, v in db["products"].items()
                if v["title"].lower() == title.lower() and v["price"] == value), None)
    if pid is None:
        pid = str(max([int(k) for k in db["products"]] + [0]) + 1)
        db["products"][pid] = {"title": title, "price": value, "cur": CODE_CUR, "stock": []}
    db["products"][pid]["stock"].extend(new)
    save(db)
    await update.message.reply_text(
        f"✅ {title} {fmt(value)} ka: {len(new)} code add. Total stock: {len(db['products'][pid]['stock'])}")


async def stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await need_admin(update):
        return
    db = load()
    if not db["products"]:
        await update.message.reply_text("Koi redeem code stock nahi.")
        return
    await update.message.reply_text("\n".join(
        f"{v['title']} | {fmt(v['price'])} ka | user pay {fmt(redeem_pay(v['price']))} {v['cur']} | stock {len(v['stock'])}"
        for v in db["products"].values()))


async def codes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/redeemcode: pehle puchta hai kitne ka chahiye."""
    if update.effective_chat.type != "private":
        await update.message.reply_text("Redeem code lene ke liye bot ko private chat me /redeemcode bhejo.")
        return
    st = PState(update.effective_user.id)
    st.clear()
    st["step"] = "code_amount"
    await update.message.reply_text(
        "🎟 Kitne ka redeem code chahiye aapko?\n"
        "Amount likho (jaise 200)\n\n"
        f"🎁 {REDEEM_DISCOUNT}% discount milega!")


async def sendcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/sendcode RC5 CODE  - jab stock me code nahi tha, payment ke baad admin code bhejta hai."""
    if not await need_admin(update):
        return
    parts = update.message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.message.reply_text("Format: /sendcode RC5 CODE")
        return
    db = load()
    o = db["orders"].get(parts[1].upper())
    if not o or o["status"] != "paid":
        await update.message.reply_text("Order nahi mila ya uska payment confirm nahi hai.")
        return
    code = parts[2].strip()
    ok = await notify(ctx, o["uid"], f"🎟 Order {o['id']} ✅\nAapka {fmt(o['price'])} ka redeem code:\n\n{code}\n\nThanks for buying from {BRAND}")
    if not ok:
        await update.message.reply_text("Buyer ko DM nahi gaya (bot block/start nahi).")
        return
    o["status"], o["code"] = "done", code
    save(db)
    await update.message.reply_text(f"✅ Order {o['id']} deliver ho gaya ({o['uname']}).")


# ---------- buttons ----------
async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    uid = user.id
    act, _, arg = q.data.partition(":")
    db = load()

    # ===== NFT deal create (seller picks currency) =====
    if act == "cur":
        if PState(uid).get("step") != "cur":
            await q.answer("Dubara /deal karo", show_alert=True)
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
        await q.edit_message_text(f"✅ Deal #{did} ban gayi aur post ho gayi.")
        return

    # ===== redeem code: buy =====
    if act == "cbuy":
        p = db["products"].get(arg)
        if not p or not p["stock"]:
            await q.answer("Stock khatam", show_alert=True)
            return
        code = p["stock"].pop(0)
        db["cn"] += 1
        oid = f"RC{db['cn']}"
        db["orders"][oid] = {
            "id": oid, "uid": uid, "uname": name_of(user), "pid": arg, "title": p["title"],
            "price": p["price"], "cur": p["cur"], "code": code, "status": "await_pay",
            "time": int(time.time()),
        }
        save(db)
        ok = await notify(ctx, uid, pay_text(oid, p["price"], p["cur"]))
        if not ok:
            # DM nahi gaya: code wapas stock me
            db["orders"][oid]["status"] = "cancelled"
            p["stock"].insert(0, code)
            save(db)
            await q.answer("Pehle bot ko private me /start karo, phir dobara Buy dabao", show_alert=True)
            return
        await q.answer("Payment details DM me bhej di")
        await notify_admins(
            ctx, f"🎟 Redeem order {oid}\n{p['title']} - {p['price']} {p['cur']}\nBuyer: {name_of(user)}",
            M([[B("✅ Payment mil gaya", callback_data=f"cpaid:{oid}"),
                B("❌ Cancel", callback_data=f"ccancel:{oid}")]]))
        return

    if act in ("cpaid", "ccancel"):
        o = db["orders"].get(arg)
        if not is_admin(uid) or not o or o["status"] != "await_pay":
            await q.answer("Not allowed", show_alert=True)
            return
        if act == "cpaid" and not o["code"]:
            o["status"] = "paid"
            save(db)
            await notify(ctx, o["uid"], f"✅ Order {o['id']}: payment confirm ho gaya. Aapka redeem code thodi der me mil jayega.")
            await mark(q, f"✅ Order {o['id']} payment confirm.\nAb {o['uname']} ko {fmt(o['price'])} ka code bhejo:\n/sendcode {o['id']} CODE")
        elif act == "cpaid":
            ok = await notify(ctx, o["uid"], f"🎟 Order {o['id']} confirm ✅\n{o['title']}\n\nYour code:\n{o['code']}\n\nThanks for buying from {BRAND}")
            if not ok:
                await q.answer("Buyer ko DM nahi gaya (bot block/start nahi)", show_alert=True)
                return
            o["status"] = "done"
            save(db)
            await mark(q, f"✅ Order {o['id']} delivered to {o['uname']}")
        else:
            o["status"] = "cancelled"
            if o["code"] and o["pid"]:
                db["products"][o["pid"]]["stock"].insert(0, o["code"])
            save(db)
            await notify(ctx, o["uid"], f"❌ Order {o['id']} cancel ho gaya.")
            await mark(q, f"❌ Order {o['id']} cancelled, code wapas stock me")
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
        await notify(ctx, d["seller"], f"#{d['id']}: {d['buyer_name']} ne buy kiya. Payment confirm hone ka wait karo.")
        await notify_admins(
            ctx, f"💳 NFT #{d['id']} - {d['item']}\nBuyer: {d['buyer_name']}\nSeller: {d['seller_name']}\n"
                 f"Amount: {d['amount']} {d['cur']}\n\nPayment aaye toh confirm karo:",
            M([[B("✅ Payment mil gaya", callback_data=f"paid:{d['id']}")]]))

    elif act == "paid":
        if not is_admin(uid) or d["status"] != "await_pay":
            await q.answer("Not allowed", show_alert=True)
            return
        gid = pick_group(db)
        if gid is None:
            await q.answer("Koi free deal group nahi! Naya group banao, bot ko admin banao aur /addgroup chalao.", show_alert=True)
            return
        try:
            exp = int(time.time()) + 86400
            l1 = await ctx.bot.create_chat_invite_link(gid, member_limit=1, expire_date=exp)
            l2 = await ctx.bot.create_chat_invite_link(gid, member_limit=1, expire_date=exp)
        except Exception:
            await q.answer("Invite link nahi bana. Bot ko us group me admin banao (Invite Users right).", show_alert=True)
            return
        d["status"], d["group"] = "in_group", gid
        d["links"] = [l1.invite_link, l2.invite_link]
        db["groups"][str(gid)]["busy"] = d["id"]
        save(db)
        await q.answer("Confirmed")
        await mark(q, f"✅ NFT #{d['id']} payment confirm, group links bhej diye.")
        await refresh(ctx, d)

        # group me deal ka panel
        try:
            await ctx.bot.send_message(
                gid,
                f"🤝 DEAL #{d['id']}\n🖼 {d['item']}\n💰 {d['amount']} {d['cur']}\n"
                f"👤 Seller: {d['seller_name']}\n🛒 Buyer: {d['buyer_name']}\n\n"
                "Payment verify ho chuka hai. Dono yahin deal complete karo.\n"
                "NFT mil jaane ke baad sirf BUYER neeche button dabaye.",
                reply_markup=M([[B("✅ NFT mil gaya - Payment release karo", callback_data=f"rel:{d['id']}")],
                                [B("⚠️ Problem / Dispute", callback_data=f"dispute:{d['id']}")]]))
        except Exception:
            pass

        for who, target, link in (("Buyer", d["buyer"], l1.invite_link), ("Seller", d["seller"], l2.invite_link)):
            text = (f"✅ Deal #{d['id']}: payment confirm ho gaya.\n"
                    f"Deal group join karo (1 baar chalne wala link):\n{link}")
            if not await notify(ctx, target, text):
                await notify_admins(ctx, f"⚠️ {who} ko DM nahi gaya (deal #{d['id']}). Ye link manually bhejo:\n{link}")

    elif act == "rel":
        if uid != d["buyer"] or d["status"] != "in_group":
            await q.answer("Sirf buyer ye button dabaa sakta hai", show_alert=True)
            return
        d["status"] = "release_req"
        save(db)
        await q.answer("Admin ko release request bhej di")
        await refresh(ctx, d)
        try:
            await q.edit_message_text(
                f"🟠 Deal #{d['id']}: buyer ne payment release maanga hai. Admin process kar raha hai.")
        except Exception:
            pass
        await notify_admins(
            ctx, f"✅ Deal #{d['id']}: buyer ne NFT confirm kiya.\n"
                 f"Seller {d['seller_name']} ko {round(d['amount'] - d['fee'], 2)} {d['cur']} release karo, "
                 "phir button dabao:",
            M([[B("📤 Released (done)", callback_data=f"release:{d['id']}")]]))

    elif act == "release":
        if not is_admin(uid) or d["status"] != "release_req":
            await q.answer("Not allowed", show_alert=True)
            return
        d["status"] = "done"
        save(db)
        await q.answer("Done")
        await mark(q, f"✅ Deal #{d['id']} complete.")
        await refresh(ctx, d)
        await notify(ctx, d["seller"], f"🎉 Deal #{d['id']} complete! {round(d['amount'] - d['fee'], 2)} {d['cur']} release ho gaye.")
        await notify(ctx, d["buyer"], f"🎉 Deal #{d['id']} complete. Thanks for using {BRAND}")
        try:
            await ctx.bot.send_message(d["group"], f"🎉 Deal #{d['id']} complete! Ye group 60 sec me khaali ho jayega.")
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
            ctx, f"⚠️ Dispute #{d['id']}\nSeller: {d['seller_name']}\nBuyer: {d['buyer_name']}\n"
                 f"Raised by: {name_of(user)}\n\n/refund {d['id']}  ya  /cancel {d['id']}")


def main():
    app = Application.builder().token(TOKEN).build()
    for name, fn in (
        ("start", start), ("myid", myid), ("deal", deal), ("mydeals", mydeals),
        ("codes", codes), ("redeemcode", codes), ("sendcode", sendcode), ("status", status), ("addcode", addcode), ("stock", stock),
        ("nft", nft_list), ("buy", nft_list), ("sell", deal),
        ("addgroup", addgroup), ("groups", groups),
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
