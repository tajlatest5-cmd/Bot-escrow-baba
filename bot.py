import os
import time
import html
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)

from emoji import e, eid
import userbot

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8713306596:AAEmmdHL26eEKpUePlQ8ZkSHTHolXOPFF14")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")  # optional: naye deal ki info yahan aayegi
COOLDOWN = 60  # seconds, ek user ke do group ke beech

DEAL_TYPES = {"p2p": "P2P", "product": "Product Deal"}
HTML = ParseMode.HTML


# ---------- texts ----------
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


# ---------- keyboards ----------
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
    """Custom emoji icons ke saath try karo, fail ho to plain buttons."""
    for icons in (True, False):
        try:
            return await send(icons)
        except BadRequest as err:
            logging.warning("send failed (icons=%s): %s", icons, err)


# ---------- handlers ----------
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
        chat_id, link, deal_id = await userbot.create_deal_group(bot_username, label)
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
        logging.exception("group welcome failed")

    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(
                LOG_CHAT_ID,
                f"New {label} deal #{deal_id} by {mention} (id {user.id})\n{link}",
                parse_mode=HTML, disable_web_page_preview=True,
            )
        except Exception:
            logging.exception("log send failed")


async def post_init(app: Application):
    await userbot.start()


async def post_shutdown(app: Application):
    await userbot.client.disconnect()


def main():
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
