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
        with open(DB_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)
    db.setdefault("n", 300)          # deal counter
    db.setdefault("cn", 0)           # redeem order counter
    db.setdefault("deals", {})
    db.setdefault("products", {})    # pid -> {title, price, cur, stock:[codes]}
    db.setdefault("orders", {})      # redeem orders
    db.setdefault("groups", {})      # gid -> {busy: deal_id|None}
    return db


def save(db):
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, DB_FILE)


# ---------- helpers ----------
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
        f"🎁 NFT & Redeem Code Bot\nProvided by {BRAND}\n\n"
        "/deal - apna NFT bechne ke liye deal banao\n"
        "/codes - redeem codes kharido\n"
        "/mydeals - meri deals aur orders\n"
        "/myid - mera Telegram ID\n\n"
        "NFT kharidne ke liye group/chat me deal card par Buy dabao."
    )


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
            out.append(f"CODE {o['id']} | {o['title'][:22]} | {o['price']} {o['cur']} | {o['status']}")
    await update.message.reply_text("\n".join(out[-20:]) if out else "Koi deal ya order nahi mila.")


# ---------- NFT deal creation (seller) ----------
async def deal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Deal banane ke liye bot ko private chat me /deal bhejo.")
        return
    if not SELLER_DEAL_ENABLED and not is_admin(update.effective_user.id):
        await update.message.reply_text("Abhi sirf admin NFT list kar sakta hai. Kharidne ke liye deal card par Buy dabao.")
        return
    ctx.user_data.clear()
    ctx.user_data["step"] = "item"
    await update.message.reply_text("🖼 NFT ka naam ya link bhejo (gift link ya @username):")


# ---------- admin: NFT add / list / delete ----------
async def addnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addnft Item | price | TON   (currency optional, default TON)
    Card usi chat me post hota hai jahan command chalaya (ya GROUP_ID me)."""
    user = update.effective_user
    if not is_admin(user.id):
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
    target = GROUP_ID or update.effective_chat.id
    m = await ctx.bot.send_message(
        target, card(d), reply_markup=M([[B("🛒 Buy", callback_data=f"buy:{did}")]]))
    d["chat"], d["mid"] = m.chat_id, m.message_id
    db["deals"][did] = d
    save(db)
    if target != update.effective_chat.id:
        await update.message.reply_text(f"✅ NFT #{did} list ho gaya.")


async def nfts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    db = load()
    rows = [d for d in db["deals"].values() if d["status"] == "open"]
    if not rows:
        await update.message.reply_text("Koi open NFT nahi hai.")
        return
    await update.message.reply_text("\n".join(
        f"#{d['id']} | {d['item'][:30]} | {d['amount']} {d['cur']} | {d['seller_name']}" for d in rows[-30:]))


async def delnft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    step = ctx.user_data.get("step")
    if update.effective_chat.type != "private" or not step:
        return
    text = update.message.text.strip()

    if step == "item":
        ctx.user_data["item"] = text
        ctx.user_data["step"] = "amount"
        await update.message.reply_text("💰 Price (sirf number) bhejo:")
    elif step == "amount":
        try:
            amt = float(text)
            if amt <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Sahi number bhejo, jaise 50")
            return
        ctx.user_data["amount"] = amt
        ctx.user_data["step"] = "cur"
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
async def addcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addcode Title | price | code1, code2, code3  (codes comma ya nayi line se)"""
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].count("|") < 2:
        await update.message.reply_text("Format:\n/addcode Google Play 100 | 100 | CODE1, CODE2")
        return
    title, price, codes = [p.strip() for p in parts[1].split("|", 2)]
    try:
        price = float(price)
    except ValueError:
        await update.message.reply_text("Price number hona chahiye.")
        return
    codes = [c.strip() for c in codes.replace("\n", ",").split(",") if c.strip()]
    if not codes:
        await update.message.reply_text("Koi code nahi mila.")
        return
    db = load()
    pid = next((k for k, v in db["products"].items() if v["title"].lower() == title.lower()), None)
    if pid is None:
        pid = str(max([int(k) for k in db["products"]] + [0]) + 1)
        db["products"][pid] = {"title": title, "price": price, "cur": CODE_CUR, "stock": []}
    db["products"][pid]["price"] = price
    db["products"][pid]["stock"].extend(codes)
    save(db)
    await update.message.reply_text(f"✅ {title}: {len(codes)} code add. Total stock: {len(db['products'][pid]['stock'])}")


async def stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    db = load()
    if not db["products"]:
        await update.message.reply_text("Koi product nahi.")
        return
    await update.message.reply_text("\n".join(
        f"{v['title']} | {v['price']} {v['cur']} | stock {len(v['stock'])}"
        for v in db["products"].values()))


async def codes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = load()
    items = [(k, v) for k, v in db["products"].items() if v["stock"]]
    if not items:
        await update.message.reply_text("Abhi koi redeem code stock me nahi hai.")
        return
    text = "🎟 REDEEM CODES\n━━━━━━━━━━━━━━\n" + "\n".join(
        f"• {v['title']} - {v['price']} {v['cur']} (stock {len(v['stock'])})" for _, v in items)
    kb = M([[B(f"🛒 Buy {v['title']} - {v['price']} {v['cur']}", callback_data=f"cbuy:{k}")] for k, v in items])
    await update.message.reply_text(text, reply_markup=kb)


# ---------- buttons ----------
async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    uid = user.id
    act, _, arg = q.data.partition(":")
    db = load()

    # ===== NFT deal create (seller picks currency) =====
    if act == "cur":
        if ctx.user_data.get("step") != "cur":
            await q.answer("Dubara /deal karo", show_alert=True)
            return
        db["n"] += 1
        did = str(db["n"])
        amt = ctx.user_data["amount"]
        d = {
            "id": did, "item": ctx.user_data["item"], "amount": amt, "cur": arg,
            "fee": fee_of(amt), "seller": uid, "seller_name": name_of(user),
            "buyer": None, "buyer_name": None, "status": "open", "time": int(time.time()),
        }
        target = GROUP_ID or q.message.chat_id
        m = await ctx.bot.send_message(
            target, card(d), reply_markup=M([[B("🛒 Buy", callback_data=f"buy:{did}")]]))
        d["chat"], d["mid"] = m.chat_id, m.message_id
        db["deals"][did] = d
        save(db)
        ctx.user_data.clear()
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
        if act == "cpaid":
            ok = await notify(ctx, o["uid"], f"🎟 Order {o['id']} confirm ✅\n{o['title']}\n\nYour code:\n{o['code']}\n\nThanks for buying from {BRAND}")
            if not ok:
                await q.answer("Buyer ko DM nahi gaya (bot block/start nahi)", show_alert=True)
                return
            o["status"] = "done"
            save(db)
            await mark(q, f"✅ Order {o['id']} delivered to {o['uname']}")
        else:
            o["status"] = "cancelled"
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
        ("codes", codes), ("addcode", addcode), ("stock", stock),
        ("addgroup", addgroup), ("groups", groups),
        ("addnft", addnft), ("nfts", nfts), ("delnft", delnft),
        ("refund", refund), ("cancel", cancel),
    ):
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
