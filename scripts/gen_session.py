"""Run this ONCE in Termux on your phone to make SESSION_STRING.
  pkg install python
  pip install telethon
  python gen_session.py
It asks for API_ID, API_HASH, your phone number and the login code Telegram sends you.
It prints a long string: copy it into the repo secret SESSION_STRING.
NEVER send this string to anyone - it is full access to your Telegram account."""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID: ").strip())
api_hash = input("API_HASH: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    s = client.session.save()
    me = client.get_me()
    print("\nLogged in as:", me.first_name)
    print("\nSESSION_STRING (copy all of it):\n")
    print(s)
    client.send_message("me", "SESSION_STRING ban gaya. Ise kisi ko mat bhejna. Ise GitHub Secrets mein daalo:\n\n" + s)
    print("\n(Ye string aapke Telegram 'Saved Messages' mein bhi bhej di hai, copy karna aasaan hoga.)")
