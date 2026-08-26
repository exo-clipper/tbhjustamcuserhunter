"""Builds data/four.txt (watchlist) and data/hot.txt (fast lane).

Watchlist = exactly-4-letter handles that satisfy ANY of:
  - real English dictionary word        (dolph popular + google-10000)
  - human first name                    (smashew NameDatabases)
  - curated brand / tech / slang term
  - generated "readable" pattern where repeated letters appear only as an
    ADJACENT pair (xxli yes, xlxi never), scored for English-likeness and
    capped so the sweep stays fast.

hot.txt = the top-N most desirable names, re-checked every ~10 s.
"""
import re
import urllib.request
from pathlib import Path

from sniper import settings

DATA = Path(__file__).parent / "data"
OUT_MAIN = DATA / "four.txt"
OUT_HOT = DATA / "hot.txt"

URLS = {
    "popular": "https://raw.githubusercontent.com/dolph/dictionary/master/popular.txt",
    "google10k": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english.txt",
    "names": "https://raw.githubusercontent.com/smashew/NameDatabases/master/NamesDatabases/first%20names/us.txt",
}

BLOCKLIST = {
    # minecraft's profanity filter rejects these, so they can never be
    # claimed - showing them would waste your time
    "anal", "anus", "arse", "bdsm", "bitch", "boob", "boobs", "boner",
    "clit", "cock", "cum", "cunt", "dago", "damn", "dick", "dild",
    "dyke", "fag", "fags", "fapp", "fuck", "gook", "homo", "horn",
    "horny", "hump", "japs", "jerk", "jizz", "kike", "kys", "nigg",
    "nude", "orgy", "penis", "porn", "prick", "pube", "puss", "queef",
    "rape", "semen", "sexy", "shag", "shags", "shit", "skank", "slut",
    "spic", "tit", "tits", "twat", "wank", "whor",
}

BRANDS = {
    "sony", "nike", "puma", "ikea", "audi", "vans", "razer", "fendi",
    "gucci", "prada", "loewe", "asics", "shein", "sonos", "cisco", "nokia",
    "volvo", "lexus", "chime", "pepsi", "fanta", "seiko", "unity", "fedex",
    "xerox", "rolex", "omega", "intel", "nikon", "delta", "apple", "tesla",
    "adobe", "nvidia", "discord", "spotify", "tiktok", "roblox", "mielle",
}

TERMS = {
    "laser", "pixel", "cyber", "logic", "nexus", "vivid", "turbo", "hyper",
    "ultra", "prime", "pulse", "quest", "realm", "shift", "spark", "surge",
    "synth", "tempo", "terra", "torch", "vapor", "vista", "voxel", "wired",
    "ember", "flint", "forge", "ghost", "haven", "ivory", "karma", "latch",
    "mirth", "nomad", "onyx", "prism", "quill", "raven", "sable", "tidal",
    "umber", "vigor", "zest", "blaze", "drift", "eagle", "frost", "glide",
    "halo", "iris", "jolt", "luna", "myth", "opal", "pyre", "rune", "sage",
    "nova", "apex", "zeal", "echo", "iris", "halcyon", "atlas", "zephyr",
}

CRYPTO = {
    "whale", "node", "coin", "mine", "stake", "chain", "blok", "yield",
    "vault", "hedge", "degen", "moon", "fork", "hash", "gwei", "ape",
    "mint", "bag", "shill", "rug", "wen",
}

SLANG = {
    "base", "sigma", "vibe", "chil", "salt", "legit", "yeet", "flex",
    "ratio", "cope", "sus", "bruh", "sheesh", "goated", "lit", "rizz",
    "gyatt", "fanum", "mew", "aura", "grind", "noob", "pog", "kekw",
}

FIRST_NAMES = {
    "emma", "liam", "noah", "olivia", "ava", "mia", "luca", "leo", "enzo",
    "aria", "ivy", "nora", "milo", "otto", "hugo", "elsa", "anna", "lena",
    "thea", "cleo", "joel", "dean", "rhys", "finn", "oskar", "axel",
    "yara", "zara", "kylo", "ren", "ash", "kai", "reign", "storm", "wolf",
}

# letters that naturally double in english words
DOUBLE_LETTERS = "bdgklmnprstzfeoo"

GEN_CAP = 1500          # max generated pattern names
HOT_SIZE = settings.HOT_MAX

VOWELS = set("aeiou")

# rough english bigram plausibility (higher = more natural)
_BIGRAMS = {
    "th": 5, "he": 5, "in": 4, "er": 4, "an": 4, "re": 4, "on": 3, "at": 3,
    "en": 3, "nd": 3, "ti": 3, "es": 3, "or": 3, "te": 3, "of": 3, "ed": 3,
    "is": 3, "it": 3, "al": 3, "ar": 3, "st": 3, "to": 3, "nt": 3, "ng": 3,
    "se": 3, "ha": 3, "as": 3, "ou": 3, "io": 3, "le": 3, "ve": 3, "co": 2,
    "me": 2, "de": 2, "hi": 2, "ri": 2, "ro": 2, "ic": 2, "ne": 2, "ea": 2,
    "ra": 2, "ce": 2, "li": 2, "ch": 2, "ll": 2, "ma": 2, "om": 2, "ur": 2,
    "ca": 2, "el": 2, "ta": 2, "la": 2, "ns": 2, "di": 2, "fo": 2, "ho": 2,
    "pe": 2, "ie": 2, "et": 2, "ss": 2, "rs": 2, "ot": 2, "un": 2, "lo": 2,
    "va": 1, "ly": 1, "vi": 1, "mo": 1, "sa": 1, "tt": 1, "ff": 1, "pp": 1,
    "rr": 1, "nn": 1, "mm": 1, "dd": 1, "gg": 1, "bb": 1, "ck": 1, "zz": 1,
}
_B_DEFAULT = 0.15


def bigram_score(w: str) -> float:
    return sum(
        _BIGRAMS.get(w[i : i + 2], _B_DEFAULT) for i in range(len(w) - 1)
    )


def has_vowel(w: str) -> bool:
    return any(c in VOWELS or c == "y" for c in w)


def double_ok(w: str) -> bool:
    """Repeated letters may only appear as one adjacent pair (xxli ok,
    xlxi never). No letter may appear more than twice."""
    for c in set(w):
        k = w.count(c)
        if k > 2:
            return False
        if k == 2 and w.rindex(c) - w.index(c) != 1:
            return False
    return True


def fetch(url: str) -> list[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": settings.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        return [ln.strip().lower() for ln in text.splitlines()]
    except OSError as e:
        print(f"  ! fetch failed {url}: {e}")
        return []


def generate_doubles() -> set[str]:
    """All 4-letter strings whose only repeats are adjacent pairs."""
    import string

    out: set[str] = set()
    alpha = string.ascii_lowercase
    others = [c for c in alpha]
    # single adjacent pair at positions (0,1), (1,2), (2,3)
    for d in DOUBLE_LETTERS:
        rest = [c for c in others if c != d]
        for pos in range(3):
            for a in rest:
                for b in rest:
                    if a == b:
                        continue
                    chars = [None, None, None, None]
                    chars[pos], chars[pos + 1] = d, d
                    free = [i for i in range(4) if chars[i] is None]
                    chars[free[0]], chars[free[1]] = a, b
                    w = "".join(chars)
                    if has_vowel(w) and w not in BLOCKLIST:
                        out.add(w)
    # two distinct adjacent pairs (aabb)
    for d1 in DOUBLE_LETTERS:
        for d2 in DOUBLE_LETTERS:
            if d1 == d2:
                continue
            w = d1 + d1 + d2 + d2
            if has_vowel(w) and w not in BLOCKLIST:
                out.add(w)
    return {w for w in out if double_ok(w)}


def main() -> None:
    print("fetching sources...")
    popular = {w for w in fetch(URLS["popular"]) if re.fullmatch(r"[a-z]+", w)}
    google = [w for w in fetch(URLS["google10k"]) if re.fullmatch(r"[a-z]+", w)]
    names_raw = fetch(URLS["names"])

    dict_words = {
        w for src in (popular, google)
        for w in src if len(w) == 4 and w not in BLOCKLIST
    }
    name_words = {
        w for w in names_raw if len(w) == 4
        and re.fullmatch(r"[a-z]+", w) and w not in BLOCKLIST
    }
    curated = {
        w for src in (BRANDS, TERMS, CRYPTO, SLANG, FIRST_NAMES)
        for w in src if len(w) == 4 and w not in BLOCKLIST
    }

    print(f"dictionary 4-letter: {len(dict_words):,}")
    print(f"first names 4-letter: {len(name_words):,}")
    print(f"curated brands/terms: {len(curated):,}")

    base = dict_words | name_words | curated

    gen = generate_doubles()
    print(f"generated adjacent-double candidates: {len(gen):,}")
    gen -= base
    gen_ranked = sorted(gen, key=lambda w: (-bigram_score(w), w))
    gen_kept = set(gen_ranked[:GEN_CAP])

    watchlist = sorted(base | gen_kept)

    # --- hot lane ranking ----------------------------------------------------
    g_rank = {w: i for i, w in enumerate(google)}

    def hot_score(w: str) -> float:
        s = 0.0
        if w in g_rank:
            s += max(0.0, (10000 - g_rank[w]) / 500)
        if w in popular:
            s += 3
        if w in BRANDS or w in TERMS:
            s += 5
        if w in FIRST_NAMES or w in name_words:
            s += 2
        if any(c + c in w for c in DOUBLE_LETTERS):
            s += 1.5
        s += bigram_score(w) / 3
        return s

    hot = sorted(watchlist, key=lambda w: (-hot_score(w), w))[:HOT_SIZE]

    OUT_MAIN.write_text("\n".join(watchlist) + "\n", encoding="utf-8")
    OUT_HOT.write_text("\n".join(hot) + "\n", encoding="utf-8")
    print(f"\nfour.txt: {len(watchlist):,} watched names")
    print(f"hot.txt : {len(hot)} fast-lane names")
    print("hot sample:", ", ".join(hot[:12]))

    assert double_ok("xxli") and not double_ok("xlxi"), "adjacency rule broken"
    assert all(double_ok(w) for w in gen_kept), "non-adjacent repeat leaked"
    print("adjacency rule check: xxli-style OK, xlxi-style rejected")


if __name__ == "__main__":
    main()
