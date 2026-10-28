"""Optional: upload big files (>50 MB, up to 2 GB) as your own Telegram account
using Telethon + a string session. Only used when API_ID, API_HASH and
SESSION_STRING secrets are all set."""
import asyncio
import os


def available() -> bool:
    return all(os.environ.get(k) for k in ("API_ID", "API_HASH", "SESSION_STRING"))


async def _send(channel_id, path, caption, kind):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(os.environ["SESSION_STRING"]),
                            int(os.environ["API_ID"]), os.environ["API_HASH"])
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("SESSION_STRING is not logged in (generate a new one)")
        await client.get_dialogs()  # fills the entity cache so the channel id resolves
        entity = await client.get_entity(int(channel_id))
        await client.send_file(entity, path, caption=caption[:1000],
                               supports_streaming=(kind == "video"),
                               force_document=(kind != "video"))
    finally:
        await client.disconnect()


def send_big(channel_id, path, caption, kind):
    asyncio.run(_send(channel_id, path, caption, kind))
