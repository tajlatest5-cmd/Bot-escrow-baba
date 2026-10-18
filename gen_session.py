"""Ek baar chalao: userbot account login karke USERBOT_SESSION string nikalo."""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID: "))
api_hash = input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as c:
    print("\nUSERBOT_SESSION=" + c.session.save())
