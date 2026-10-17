import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "8713306596:AAF6OCgWK9NkfmuB-ScOZc1wEPKvbHLpplI")

START_TEXT = (
    "🎆 <b>P.A.G.A.L World Group Chat</b> 🎆\n\n"
    "🔗 Link : https://t.me/+RPxCwPjiGFxhMTk1 ✅\n\n"
    "Managed By - P.A.G.A.L World Management Team🥂\n\n"
    "Escrow : @PWEscrowBot ✅\n"
    "P2P Group : @PW_P2P ✅\n"
    "Updates : @BSR_ShoppiE ✅\n"
    "Escrow : @PWEscrow ✅\n"
    "Support : @PW_AssistBot ✅\n\n"
    "<b>JOIN ALL 🔗</b>"
)

KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔗 Group Chat", url="https://t.me/+RPxCwPjiGFxhMTk1")],
    [
        InlineKeyboardButton("Escrow Bot", url="https://t.me/PWEscrowBot"),
        InlineKeyboardButton("P2P Group", url="https://t.me/PW_P2P"),
    ],
    [
        InlineKeyboardButton("Updates", url="https://t.me/BSR_ShoppiE"),
        InlineKeyboardButton("Escrow", url="https://t.me/PWEscrow"),
    ],
    [InlineKeyboardButton("Support", url="https://t.me/PW_AssistBot")],
])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        START_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=KEYBOARD,
        disable_web_page_preview=True,
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
