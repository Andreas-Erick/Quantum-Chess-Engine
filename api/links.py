"""The formats of game links, shared by the server's tools and the desktop app.

The UI reads and builds the same formats in ``ui/src/links.ts``; change both together.

* ``<origin>/?game=<id>`` opens a game, ``<origin>/?join=<id>`` invites a friend to join it.
* ``#seat=<color>.<token>`` hands a seat to the page in the fragment, which browsers never send
  to a server. The desktop app uses it after joining a game itself.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlsplit


def game_id_from_link(link: str) -> Optional[str]:
    """The game a link opens or invites to (``?game=`` or ``?join=``), if any."""
    query = parse_qs(urlsplit(link.strip()).query)
    values = query.get("game") or query.get("join")
    return values[0] if values else None


def seat_fragment(color: str, token: str) -> str:
    """The fragment that hands a seat to the page: ``#seat=<color>.<token>``."""
    return f"#seat={color}.{token}"
