"""The one place that decides a name is unclaimable for profanity reasons.

Mojang runs its own filter when you submit a name change, so a name it
refuses is worthless to us no matter how free the API says it is. Showing
one wastes your time, which is the only reason this module exists.

Two rules keep it honest:
  * only genuinely offensive words go in data/blocked.txt - not every word
    that merely sounds edgy;
  * matching is EXACT, never substring, so "anal" can never hide "canal".

Add words without touching the repo by setting the BLOCK_EXTRA secret
(comma separated), or locally with `python main.py block <word ...>`.
"""
import os
from pathlib import Path

DATA = Path(__file__).parent / "data"
FILE = DATA / "blocked.txt"

_cache: frozenset[str] | None = None


def _from_env() -> set[str]:
    raw = os.environ.get("BLOCK_EXTRA", "").replace("\n", ",")
    return {w.strip().lower() for w in raw.split(",") if w.strip()}


def _from_file() -> set[str]:
    if not FILE.exists():
        return set()
    words = set()
    for line in FILE.read_text(encoding="utf-8").splitlines():
        word = line.split("#", 1)[0].strip().lower()
        if word:
            words.add(word)
    return words


def blocked() -> frozenset[str]:
    global _cache
    if _cache is None:
        _cache = frozenset(_from_file() | _from_env())
    return _cache


def is_blocked(name: str) -> bool:
    return name.strip().lower() in blocked()


def add(words: list[str]) -> list[str]:
    """Append new words to data/blocked.txt; returns the ones actually added."""
    global _cache
    have = blocked()
    fresh = sorted({w.strip().lower() for w in words if w.strip()} - have)
    if fresh:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(FILE, "a", encoding="utf-8") as f:
            f.write("\n# added manually\n" + "\n".join(fresh) + "\n")
        _cache = None
    return fresh
