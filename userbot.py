"""Telegram bots khud group nahi bana sakte, isliye ek dedicated user account
(Telethon) group banata hai, bot ko admin banata hai aur invite link deta hai."""
import os
import uuid

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

API_ID = int(os.getenv("34145046, "0"))
API_HASH = os.getenv("9eef1f689e6bde55fa0240660f7222ca", "")
SESSION = os.getenv("USERBOT_SESSION", "")
INVITE_LIMIT = int(os.getenv("INVITE_LIMIT", "3"))  # link max kitne log use kar sakte

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


async def start():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Userbot session invalid. gen_session.py chalao.")


async def create_deal_group(bot_username: str, label: str):
    """New private group banata hai. Returns (bot_chat_id, invite_link, deal_id)."""
    deal_id = uuid.uuid4().hex[:6].upper()
    result = await client(CreateChannelRequest(
        title=f"{label} Deal #{deal_id}",
        about="Don Escrow Service - private deal group",
        megagroup=True,
    ))
    channel = result.chats[0]

    bot_entity = await client.get_entity(bot_username)
    await client(InviteToChannelRequest(channel, [bot_entity]))
    await client.edit_admin(
        channel, bot_entity,
        change_info=True, delete_messages=True, ban_users=True,
        invite_users=True, pin_messages=True,
    )

    invite = await client(ExportChatInviteRequest(channel, usage_limit=INVITE_LIMIT))
    return utils.get_peer_id(channel), invite.link, deal_id
