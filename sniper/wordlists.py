import re
import zlib
from pathlib import Path

from .blocklist import is_blocked

DATA = Path(__file__).parent / "data"

PLATFORMS = ("minecraft",)

_FILES = ("four.txt", "extras.txt")

_RULES = {
    # what minecraft itself accepts (we only watch 4-letter alpha names)
    "minecraft": re.compile(r"^[a-z0-9_]{3,16}$"),
}


def valid_for(platform: str, name: str) -> bool:
    """Could minecraft actually hand you this name? Format plus the
    profanity filter - a name mojang refuses is not worth watching."""
    if not _RULES[platform].match(name):
        return False
    return not is_blocked(name)


def load_names(platform: str) -> list[str]:
    names: set[str] = set()
    for f in _FILES:
        p = DATA / f
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                n = line.strip().lower()
                if n and valid_for(platform, n):
                    names.add(n)
    return sorted(names)


def load_hot(idx: int, cnt: int) -> list[str]:
    """This shard's slice of the fast lane (consistent crc sharding)."""
    p = DATA / "hot.txt"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        n = line.strip().lower()
        if not n or is_blocked(n):
            continue
        if cnt <= 1 or zlib.crc32(n.encode()) % cnt == idx:
            out.append(n)
    return out
