"""Builds data/five.txt: quality 5-letter Telegram handles.

Sources (all free, fetched at build time):
  - dolph/dictionary popular.txt      (common English)
  - first20hours google-10000        (frequency-ranked English)
  - smashew/NameDatabases us names   (first names)
plus curated Web3/slang, brand, and first-name supplements.
"""
import re
import string
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
OUT = DATA / "five.txt"

URLS = {
    "popular": "https://raw.githubusercontent.com/dolph/dictionary/master/popular.txt",
    "google10k": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english.txt",
    "names": "https://raw.githubusercontent.com/smashew/NameDatabases/master/NamesDatabases/first%20names/us.txt",
}

BLOCKLIST = {
    "penis", "bitch", "fucks", "fucked", "shits", "cunts", "whore", "whores",
    "dildo", "dildos", "raped", "rapes", "pornos", "jizz", "spunk", "wanks",
    "boner", "horny", "sluts", "nigga", "niggas", "fagg", "kikes", "spics",
    "coons", "towel", "dykes", "pussy", "twats", "balls", "boned", "clits",
}

CRYPTO = {
    "alpha", "whale", "nodes", "token", "coins", "miner", "stake", "staked",
    "chain", "block", "yield", "asset", "vault", "hedge", "ether", "degen",
    "lunar", "orbit", "satosh", "minty", "forks", "hashr", "gweis",
}

SLANG = {
    "based", "sigma", "vibes", "chill", "salty", "legit", "goated", "yeets",
    "susss", "litaf", "flexn", "ratio", "copez",
}

BRANDS = {
    "apple", "tesla", "rolex", "intel", "nikon", "gucci", "prada", "fendi",
    "delta", "adidas", "reebok", "asics", "shein", "sonos", "cisco", "nokia",
    "volvo", "lexus", "chime", "pepsi", "fanta", "coach", "loewe", "omega",
    "seiko", "razer", "sonic", "mario", "zelda", "unity", "fedex", "visio",
    "xerox", "kluge",
}

TERMS = {
    "laser", "robot", "solar", "pixel", "cyber", "logic", "nexus", "vivid",
    "turbo", "hyper", "ultra", "prime", "pulse", "quest", "realm", "shift",
    "spark", "surge", "synth", "tempo", "terra", "torch", "vapor", "vista",
    "voxel", "wired", "ember", "flint", "forge", "ghost", "haven", "ivory",
    "jade", "karma", "latch", "mirth", "nomad", "onyx", "prism", "quill",
    "raven", "sable", "tidal", "umber", "vigor", "warden", "xenon", "yacht",
    "zesty", "blaze", "clover", "drift", "eagle", "frost", "glide", "harbor",
    "index", "joust", "koala", "lotus", "maple", "noble", "opals", "pearl",
    "quiet", "ridge", "storm", "tiger", "umbra", "velvet", "waltz", "zephy",
}

FIRST_NAMES = {
    "david", "sarah", "james", "pavel", "emily", "grace", "chloe", "aaron",
    "naomi", "alice", "clara", "elena", "nadia", "farah", "layla", "oscar",
    "felix", "louis", "henry", "peter", "simon", "kevin", "brian", "lucas",
    "jonas", "anton", "maxim", "artur", "arman", "timur", "alina", "leyla",
    "fatma", "ahmet", "yusuf", "hamza", "maria", "lucia", "amara", "zaria",
    "kaia", "nia", "talia", "selin", "deniz", "esra", "merve", "irem",
    "noor", "layan", "rana", "sami", "omar", "kareem", "malik", "tariq",
    "jamal", "karim", "nadia", "amina", "yasmin", "salma", "hind", "reem",
}

GUARANTEE = {
    "royal", "yield", "asset", "coins", "agent", "alpha", "whale", "nodes",
    "track", "apple", "tesla", "rolex", "intel", "david", "sarah", "james",
    "pavel",
}

VOWELS = set("aeiou")


def readable(word: str) -> bool:
    if not word.isalpha():
        return False
    if not any(c in VOWELS or c == "y" for c in word):
        return False
    run = 0
    for ch in word:
        if ch in VOWELS or ch == "y":
            run = 0
        else:
            run += 1
            if run > 3:
                return False
    return True


def fetch(url: str) -> list[str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        return [ln.strip().lower() for ln in text.splitlines()]
    except OSError as e:
        print(f"  ! fetch failed {url}: {e}")
        return []


def main() -> None:
    words: set[str] = set()
    words |= {w for w in CRYPTO | SLANG | BRANDS | TERMS | FIRST_NAMES if len(w) == 5}
    words |= GUARANTEE

    for key in ("popular", "google10k", "names"):
        lines = fetch(URLS[key])
        kept = [
            w for w in lines
            if len(w) == 5 and re.fullmatch(r"[a-z]+", w) and readable(w) and w not in BLOCKLIST
        ]
        print(f"{key}: +{len(kept):,}")
        words.update(kept)

    words = {w for w in words if len(w) == 5 and readable(w) and w not in BLOCKLIST}
    ordered = sorted(words)

    OUT.write_text("\n".join(ordered) + "\n", encoding="utf-8")
    print(f"\nfive.txt: {len(ordered):,} names")

    missing = [w for w in sorted(GUARANTEE) if w not in words]
    print("examples check:", "ALL PRESENT" if not missing else f"MISSING {missing}")


if __name__ == "__main__":
    main()
