"""
Group Deal Bot (Telegram)
Commands: /add /close /hold /release /refund /feedback /fee /deals
Har group ka data alag (chat_id ke hisaab se) store hota hai.
Note: Yeh bot sirf deals ka record/status track karta hai, asli paisa handle nahi karta.
"""
import os
import sqlite3
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["9116340475:AAEmRvbHQMW7z98ROg7exZPXaFIMD3hnLdA"]
OWNER_ID = int(os.getenv("OWNER_ID", "7054168366"))          # feedback yahan forward hoga (optional)
DEFAULT_FEE = float(os.getenv("DEFAULT_FEE", "5"))  # percent
DB_PATH = os.getenv("DB_PATH", "bot.db")


# ---------- Database ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS deals (
                chat_id INTEGER NOT NULL,
                deal_id INTEGER NOT NULL,
                buyer TEXT, seller TEXT,
                amount REAL NOT NULL,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, deal_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                chat_id INTEGER PRIMARY KEY,
                fee_percent REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER, user_id INTEGER, username TEXT,
                text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def get_fee(chat_id: int) -> float:
    with db() as c:
        row = c.execute("SELECT fee_percent FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
    return row["fee_percent"] if row else DEFAULT_FEE


def get_deal(chat_id: int, deal_id: int):
    with db() as c:
        return c.execute(
            "SELECT * FROM deals WHERE chat_id=? AND deal_id=?", (chat_id, deal_id)
        ).fetchone()


def set_status(chat_id: int, deal_id: int, status: str):
    with db() as c:
        c.execute(
            "UPDATE deals SET status=? WHERE chat_id=? AND deal_id=?",
            (status, chat_id, deal_id),
        )


# ---------- Helpers ----------
async def require_group(update: Update) -> bool:
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("Yeh command sirf group me kaam karta hai.")
        return False
    return True


async def require_admin(update: Update) -> bool:
    if not await require_group(update):
        return False
    member = await update.effective_chat.get_member(update.effective_user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("Sirf group admin yeh command use kar sakta hai.")
        return False
    return True


def parse_deal_id(args):
    if not args or not args[0].lstrip("#").isdigit():
        return None
    return int(args[0].lstrip("#"))


def fmt(n: float) -> str:
    return f"{n:,.2f}"


async def transition(update, ctx, command, allowed_from, new_status, verb):
    """Common logic for /hold /release /refund /close."""
    if not await require_admin(update):
        return
    deal_id = parse_deal_id(ctx.args)
    if deal_id is None:
        await update.message.reply_text(f"Use: /{command} <deal_id>\nExample: /{command} 1")
        return
    chat_id = update.effective_chat.id
    deal = get_deal(chat_id, deal_id)
    if not deal:
        await update.message.reply_text(f"Deal #{deal_id} is group me nahi mili.")
        return
    if deal["status"] not in allowed_from:
        await update.message.reply_text(
            f"Deal #{deal_id} ka status '{deal['status']}' hai, isliye /{command} nahi ho sakta.\n"
            f"Allowed status: {', '.join(allowed_from)}"
        )
        return

    set_status(chat_id, deal_id, new_status)
    text = f"✅ Deal #{deal_id} {verb}.\nAmount: {fmt(deal['amount'])}"

    if command == "release":
        fee_pct = get_fee(chat_id)
        fee = deal["amount"] * fee_pct / 100
        text += (
            f"\nFee ({fee_pct:g}%): {fmt(fee)}"
            f"\nSeller ko payout: {fmt(deal['amount'] - fee)}"
            f"\nSeller: {deal['seller']}"
        )
    elif command == "refund":
        text += f"\nBuyer ko refund: {fmt(deal['amount'])}\nBuyer: {deal['buyer']}"
    await update.message.reply_text(text)


# ---------- Commands ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Group Deal Bot\n\n"
        "/add @buyer @seller <amount> [note] - nayi deal (admin)\n"
        "/hold <id> - amount hold karo (admin)\n"
        "/release <id> - seller ko release (admin)\n"
        "/refund <id> - buyer ko refund (admin)\n"
        "/close <id> - deal band karo (admin)\n"
        "/deals - is group ki deals\n"
        "/fee <amount> - fee calculate karo\n"
        "/fee set <percent> - group fee set (admin)\n"
        "/feedback <message> - feedback bhejo"
    )


async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text("Use: /add @buyer @seller <amount> [note]")
        return
    buyer, seller = args[0], args[1]
    try:
        amount = float(args[2].replace(",", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Amount sahi number hona chahiye (0 se zyada).")
        return
    note = " ".join(args[3:]) or "-"
    chat_id = update.effective_chat.id

    with db() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(deal_id),0)+1 AS nid FROM deals WHERE chat_id=?", (chat_id,)
        ).fetchone()
        deal_id = row["nid"]
        c.execute(
            "INSERT INTO deals (chat_id, deal_id, buyer, seller, amount, note, created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (chat_id, deal_id, buyer, seller, amount, note, update.effective_user.id),
        )
    fee_pct = get_fee(chat_id)
    await update.message.reply_text(
        f"📝 Deal #{deal_id} bani\n"
        f"Buyer: {buyer}\nSeller: {seller}\n"
        f"Amount: {fmt(amount)}\nFee: {fee_pct:g}% ({fmt(amount * fee_pct / 100)})\n"
        f"Note: {note}\nStatus: open"
    )


async def hold(update, ctx):
    await transition(update, ctx, "hold", ("open",), "held", "hold par rakhi gayi")


async def release(update, ctx):
    await transition(update, ctx, "release", ("held",), "released", "release ho gayi")


async def refund(update, ctx):
    await transition(update, ctx, "refund", ("held",), "refunded", "refund ho gayi")


async def close(update, ctx):
    await transition(
        update, ctx, "close", ("open", "released", "refunded"), "closed", "close ho gayi"
    )


async def deals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return
    with db() as c:
        rows = c.execute(
            "SELECT * FROM deals WHERE chat_id=? ORDER BY deal_id DESC LIMIT 15",
            (update.effective_chat.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text("Is group me abhi koi deal nahi hai.")
        return
    lines = [
        f"#{r['deal_id']} | {r['buyer']} → {r['seller']} | {fmt(r['amount'])} | {r['status']}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines))


async def fee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = ctx.args

    # /fee set 5
    if args and args[0].lower() == "set":
        if not await require_admin(update):
            return
        try:
            pct = float(args[1])
            if not 0 <= pct <= 100:
                raise ValueError
        except (IndexError, ValueError):
            await update.message.reply_text("Use: /fee set <percent>  (0-100)")
            return
        with db() as c:
            c.execute(
                "INSERT INTO settings (chat_id, fee_percent) VALUES (?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET fee_percent=excluded.fee_percent",
                (chat_id, pct),
            )
        await update.message.reply_text(f"✅ Is group ki fee ab {pct:g}% hai.")
        return

    pct = get_fee(chat_id)
    if not args:
        await update.message.reply_text(
            f"Current fee: {pct:g}%\nCalculate karne ke liye: /fee <amount>"
        )
        return
    try:
        amount = float(args[0].replace(",", ""))
    except ValueError:
        await update.message.reply_text("Use: /fee <amount>")
        return
    f = amount * pct / 100
    await update.message.reply_text(
        f"Amount: {fmt(amount)}\nFee ({pct:g}%): {fmt(f)}\nSeller ko milega: {fmt(amount - f)}"
    )


async def feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    if not text:
        await update.message.reply_text("Use: /feedback <aapka message>")
        return
    user = update.effective_user
    with db() as c:
        c.execute(
            "INSERT INTO feedback (chat_id, user_id, username, text) VALUES (?,?,?,?)",
            (update.effective_chat.id, user.id, user.username, text),
        )
    if OWNER_ID:
        try:
            await ctx.bot.send_message(
                OWNER_ID,
                f"📩 Feedback from @{user.username or user.id} "
                f"(chat {update.effective_chat.id}):\n{text}",
            )
        except Exception as e:  # owner ne bot start nahi kiya ho sakta hai
            logging.warning("Owner ko feedback nahi bhej paya: %s", e)
    await update.message.reply_text("🙏 Feedback ke liye shukriya!")


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    for name, fn in [
        ("start", start), ("help", start),
        ("add", add), ("hold", hold), ("release", release),
        ("refund", refund), ("close", close), ("deals", deals),
        ("fee", fee), ("feedback", feedback),
    ]:
        app.add_handler(CommandHandler(name, fn))
    app.run_polling()


if __name__ == "__main__":
    main()
