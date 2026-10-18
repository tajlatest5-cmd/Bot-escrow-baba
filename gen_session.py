"""Ek baar chalao: userbot account login karke USERBOT_SESSION string nikalo."""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input(" 34145046 "))
api_hash = input(" 9eef1f689e6bde55fa0240660f7222ca ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as c:
    print("\nUSERBOT_SESSION=" + c.session.save())
