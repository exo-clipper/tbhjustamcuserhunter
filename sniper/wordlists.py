import re
from pathlib import Path

DATA = Path(__file__).parent / "data"

PLATFORMS = ("telegram",)

_FILES = ("five.txt", "extras.txt")

_RULES = {
    # >=3 chars; note: on telegram anything under 5 chars is auctioned via
    # fragment rather than freely claimable, but we still watch for changes
    "telegram": re.compile(r"^[a-z][a-z0-9_]{2,31}$"),
}


def valid_for(platform: str, name: str) -> bool:
    return bool(_RULES[platform].match(name))


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
