"""Live check of the video-site adapter (needs internet, no Telegram):
  python scripts/live_check.py https://videoclasses.vercel.app/
Lists the files the bot would send and downloads the smallest one to check it."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import adapters  # noqa: E402
from bot.main import download  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "https://videoclasses.vercel.app/"
name, items = adapters.list_items(url)
print(f"adapter: {name}, files: {len(items)}")
for it in items:
    print(" -", it.id, it.size, it.caption)
if items:
    it = min(items, key=lambda i: i.size or 1 << 40)
    d = tempfile.mkdtemp()
    path, size = download(it, d)
    print("downloaded", path, size, "bytes")
