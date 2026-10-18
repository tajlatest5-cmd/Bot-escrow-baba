import os
import re
import asyncio
import logging
import time
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    CreateChatRequest,
    ExportChatInviteRequest,
)

# ---------- CONFIGURATION ----------

BOT_TOKEN = os.environ["8713306596:AAEmmdHL26eEKpUePlQ8ZkSHTHolXOPFF14"]
API_ID = int(os.environ["34145046"]
API_HASH = os.environ["9eef1f689e6bde55fa0240660f7222ca"]
USER_SESSION = os.environ["1AZWarzQBuynh2jMmOumHufr10ekAqgnZ7hkNjzdxxIhbsNAl5y5u0HDd9p0_XcUJi295fuKnmXE7jZqV2rmwikZaDlsLOINBIBxegsDGpsZZ8QLc5Q0FWeC8W32VibhyAkqsMLarxxdCHkYJDkqppUPq-y0jNWAxOBHBGTdkqE9WhPjAq7ZCbyB5k9F4GHsxPDIyuo0TWZ9pxtw8vTqrM3CAlzphHligzz2iAL76KCRml_h4-ygcWCEsOI93ukfZ5BVtLmlEHKf8pvqB8GLuClCNuCQJpP3e47yLXd52c-ZwhKDqhN0F6kkR09zJ_s9zkTz9JFzZVe1y8Wp2_9w4DdKagZRDAuA="]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

# Connected Telegram account creates the groups.
client = TelegramClient(
    StringSession(USER_SESSION),
    API_ID,
    API_HASH,
)

DEAL_TYPES = {
    "p2p": "P2P",
    "product": "Product Deal",
}

# Simple in-memory cooldown: one request per user per 10 minutes.
last_request = {}
COOLDOWN_SECONDS = 600


# ---------- START COMMAND ----------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    keyboard = [
        [
            InlineKeyboardButton(
                "P2P",
                callback_data="p2p",
            )
        ],
        [
            InlineKeyboardButton(
                "Product Deal",
                callback_data="product",
            )
        ],
    ]

    welcome = (
        "Welcome to Don Escrow Service\n\n"
        "Escrow : @xDonEscrow\n"
        "P2P Group : @PW_P2P\n"
        "Detail : @BSR_ShoppiE\n"
        "Customer help : @PW_AssistBot\n\n"
        "Please select your escrow type from below."
    )

    await update.effective_message.reply_text(
        welcome,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------- SELECT DEAL TYPE ----------

async def select_type(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    deal_type = DEAL_TYPES.get(query.data)

    if deal_type is None:
        await query.message.reply_text(
            "Invalid selection. Send /start to try again."
        )
        return

    context.user_data["deal_type"] = deal_type

    await query.message.reply_text(
        f"Selected: {deal_type}\n\n"
        "Send the buyer and seller usernames in one message.\n\n"
        "Example:\n"
        "@buyer_username @seller_username\n\n"
        "Both usernames must belong to the correct participants."
    )


# ---------- CREATE PRIVATE GROUP ----------

async def create_deal_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    deal_type = context.user_data.get("deal_type")

    if not deal_type:
        return

    message = update.effective_message
    telegram_user = update.effective_user

    if not telegram_user:
        return

    # Prevent rapid repeated requests from the same user.
    now = time.monotonic()
    previous = last_request.get(telegram_user.id, 0)

    if now - previous < COOLDOWN_SECONDS:
        remaining = int(
            COOLDOWN_SECONDS - (now - previous)
        )
        await message.reply_text(
            f"Please wait {remaining} seconds before another request."
        )
        return

    usernames = re.findall(
        r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{4,31}",
        message.text or "",
    )

    usernames = list(dict.fromkeys(usernames))

if len(usernames) != 2:
        await message.reply_text(
            "Please send exactly two usernames.\n\n"
            "Example: @buyer_username @seller_username"
        )
        return

    # Set cooldown before making Telegram API requests.
    last_request[telegram_user.id] = now

    await message.reply_text(
        "Creating your private escrow group. Please wait..."
    )

    try:
        async with asyncio.timeout(60):
            # Resolve usernames through the connected account.
            buyer_entity = await client.get_entity(usernames[0])
            seller_entity = await client.get_entity(usernames[1])

            if not getattr(buyer_entity, "username", None):
                raise ValueError("Buyer username could not be verified.")

            if not getattr(seller_entity, "username", None):
                raise ValueError("Seller username could not be verified.")

            buyer = utils.get_input_user(buyer_entity)
            seller = utils.get_input_user(seller_entity)

            title = (
                f"Don Escrow | {deal_type} | "
                f"{datetime.now().strftime('%d-%m-%Y %H:%M')}"
            )

            # Create a new Telegram group.
            result = await client(
                CreateChatRequest(
                    users=[buyer, seller],
                    title=title,
                )
            )

            chats = getattr(result, "chats", [])

            if not chats:
                raise RuntimeError(
                    "Telegram did not return the created group."
                )

            group = chats[0]

            # Export an invite link for the new group.
            invite = await client(
                ExportChatInviteRequest(peer=group)
            )

            context.user_data.pop("deal_type", None)

            await message.reply_text(
                "PRIVATE ESCROW GROUP CREATED\n\n"
                f"Deal Type: {deal_type}\n"
                f"Buyer: @{buyer_entity.username}\n"
                f"Seller: @{seller_entity.username}\n\n"
                "Group Invite Link:\n"
                f"{invite.link}\n\n"
                "Share this link only with the intended participants."
            )

    except asyncio.TimeoutError:
        logger.warning("Group creation timed out.")

        await message.reply_text(
            "The request timed out. Check Telegram and try again later."
        )

    except Exception:
        # Keep private session details out of user-facing messages.
        logger.exception("Private group creation failed.")

        await message.reply_text(
            "Unable to create the group or generate its invite link.\n\n"
            "Check the usernames and Telegram account restrictions. "
            "If a group was already created, check your Telegram chats "
            "before retrying."
        )


# ---------- APPLICATION ----------

async def main():
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "USER_SESSION is not authorized. Generate a new session."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(
            select_type,
            pattern=r"^(p2p|product)$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            create_deal_group,
        )
    )

    try:
        await app.initialize()
        await app.start()

        if app.updater is None:
            raise RuntimeError("Telegram polling is unavailable.")

        await app.updater.start_polling()

        logger.info("Don Escrow Service bot is running.")

        await asyncio.Event().wait()

    finally:
        if app.updater and app.updater.running:
            await app.updater.stop()

        await app.stop()
        await app.shutdown()
        await client.disconnect()

if name == "main":
    asyncio.run(main())
