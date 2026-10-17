import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes

from emoji import e, eid

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8082719676:AAF5n670oue3ENN6r2puO8LjXcqjFa6INdU")


def start_text() -> str:
    return (
        f"{e('party')} <b>Welcome to Don Escrow Service</b> {e('party')}\n\n"
        f"{e('shield')} Escrow : @xDonEscrow {e('check')}\n"
        f"{e('chat')} P2P Group : @PW_P2P {e('check')}\n"
        f"{e('info')} Detail : @BSR_ShoppiE {e('check')}\n"
        f"{e('support')} Customer help : @PW_AssistBot {e('check')}"
    )


def btn(label: str, url: str, icon: str, icons: bool) -> InlineKeyboardButton:
    if icons:
        return InlineKeyboardButton(label, url=url, api_kwargs={"icon_custom_emoji_id": eid(icon)})
    return InlineKeyboardButton(label, url=url)


def keyboard(icons: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("Escrow", "https://t.me/xDonEscrow", "shield", icons)],
        [btn("P2P Group", "https://t.me/PW_P2P", "chat", icons)],
        [btn("Detail", "https://t.me/BSR_ShoppiE", "info", icons)],
        [btn("Customer help", "https://t.me/PW_AssistBot", "support", icons)],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pehle custom emoji (text + button icons) try karo, fail ho to plain fallback.
    attempts = [(start_text(), True), (start_text(), False)]
    for text, icons in attempts:
        try:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard(icons),
                disable_web_page_preview=True,
            )
            return
        except BadRequest as err:
            logging.warning("start send failed (icons=%s): %s", icons, err)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
