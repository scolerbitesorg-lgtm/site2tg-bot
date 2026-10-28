from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Item:
    """One file found on a site."""
    id: str                      # stable id used to remember "already sent"
    url: str                     # direct download URL (may carry a short-lived token)
    filename: str                # name to give the file in Telegram
    caption: str = ""
    size: Optional[int] = None   # bytes, if the site tells us
    headers: dict = field(default_factory=dict)  # extra headers for the download (e.g. Referer)
    kind: str = "document"       # "video" or "document"
