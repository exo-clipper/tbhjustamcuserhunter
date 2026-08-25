"""Builds the watchlists from raw sources.

Outputs:
  data/three.txt   - all 17,576 three-letter combos
  data/words4.txt  - readable four-letter names
  data/words5.txt  - readable five-letter names (Telegram's minimum length)
"""
from itertools import product
from pathlib import Path
import string

DATA = Path(__file__).parent / "data"
FREQ = Path(Path(__file__).parent / "words_alpha.txt") if False else None

VOWELS = set("aeiou")


def readable(word: str) -> bool:
    if not word.isalpha():
        return False
    if not (VOWELS & set(word)) and "y" not in word:
        return False
    run = 0
    for ch in word:
        if ch in VOWELS or (ch == "y" and run < 1):
            run = 0
        else:
            run += 1
            if run > 3:
                return False
    return True


def build_three() -> list[str]:
    return ["".join(c) for c in product(string.ascii_lowercase, repeat=3)]


def load_lines(p: Path) -> list[str]:
    text = p.read_text(encoding="utf-8", errors="ignore")
    return [ln.strip().lower() for ln in text.splitlines() if ln.strip()]


def build_four_or_five(freq_path: Path, dict_path: Path, length: int) -> list[str]:
    freq = {w for w in load_lines(freq_path) if len(w) == length and w.isalpha()}
    dictionary = {w for w in load_lines(dict_path) if len(w) == length}
    return sorted(freq | {w for w in dictionary if readable(w)})


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", required=True)
    ap.add_argument("--dict", required=True)
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)

    three = build_three()
    (DATA / "three.txt").write_text("\n".join(three) + "\n", encoding="utf-8")
    print(f"three.txt : {len(three):,} combos")

    for n in (4, 5):
        words = build_four_or_five(Path(args.freq), Path(args.dict), n)
        (DATA / f"words{n}.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
        print(f"words{n}.txt: {len(words):,} readable words")

    four = set(load_lines(DATA / "words4.txt"))
    for probe in ("murk", "down", "high", "kvps"):
        print(f"  {probe!r} included: {probe in four}")


if __name__ == "__main__":
    main()
