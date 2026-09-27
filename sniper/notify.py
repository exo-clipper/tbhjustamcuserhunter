"""Telegram alerts for notable (worth-claiming) 4-letter frees.

A name is "notable" if it is in data/notable.txt (built by
build_wordlists.py: real words, human names, brands, terms - NOT the
generated pattern junk) or in the ALERT_EXTRA secret (comma-separated
personal picks, e.g. "moki,looo").

Alerts fire on the TRANSITION into claimable (a check or history probe
that flips a name's state), never on routine re-checks, so a name that
stays free for hours produces exactly one message. Sends are queued and
delivered by a background task; a failure retries once and then gives up
without ever blocking the watcher loop. Disabled entirely (and silent)
when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set.
"""
import asyncio
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .blocklist import is_blocked

DATA = Path(__file__).parent / "data"
NOTABLE_FILE = DATA / "notable.txt"

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ENABLED = bool(_TOKEN and _CHAT)


def _extra() -> set[str]:
    raw = os.environ.get("ALERT_EXTRA", "")
    return {w.strip().lower() for w in raw.split(",") if w.strip()}


def load_notable() -> set[str]:
    """Everything worth an alert: the curated notable list + personal picks."""
    out: set[str] = set(_extra())
    if NOTABLE_FILE.exists():
        for line in NOTABLE_FILE.read_text(encoding="utf-8").splitlines():
            n = line.strip().lower()
            if n and not is_blocked(n):
                out.add(n)
    return out


NOTABLE: set[str] = load_notable()

_queue: asyncio.Queue | None = None
_sent: set[str] = set()


def is_notable(name: str) -> bool:
    return name.lower() in NOTABLE


def enqueue(name: str) -> None:
    """Queue a telegram alert for a notable name that just became claimable.

    Fire-and-forget from the watcher loop: never blocks, never raises, does
    nothing when telegram is unconfigured, the name is not notable, or this
    name was already alerted during this run."""
    if not ENABLED:
        return
    name = name.lower()
    if name not in NOTABLE or name in _sent:
        return
    _sent.add(name)
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
        asyncio.get_running_loop().create_task(_sender())
    _queue.put_nowait(name)


def _send(name: str) -> None:
    """Blocking telegram sendMessage (runs in a worker thread)."""
    text = (f"\U0001F7E2 {name} is claimable RIGHT NOW\n"
            "grab it: https://www.minecraft.net/en-us/profile")
    data = urllib.parse.urlencode({
        "chat_id": _CHAT, "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_TOKEN}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"telegram http {resp.status}")


async def _sender() -> None:
    while True:
        name = await _queue.get()
        for attempt in (1, 2):
            try:
                await asyncio.to_thread(_send, name)
                break
            except Exception as e:
                print(f"[notify] telegram attempt {attempt} failed: {e}",
                      flush=True)
                await asyncio.sleep(3)