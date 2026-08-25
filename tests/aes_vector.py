import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sniper import aeslite


def main() -> int:
    key = bytes(range(32))
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    words = aeslite._expand_key(key)
    got = aeslite.encrypt_block(pt, words).hex()
    want = "8ea2b7ca516745bfeafc49904b496089"
    print(f"{'PASS' if got == want else 'FAIL'} fips-197 aes-256 vector: {got}")
    if got != want:
        return 1

    k = os.urandom(32)
    iv = os.urandom(16)
    msg = os.urandom(53)
    ct = aeslite.encrypt_cbc(k, iv, msg)
    print(
        f"{'PASS' if len(ct) == 64 else 'FAIL'} pkcs7 padding size: {len(ct)}"
    )
    return 0 if len(ct) == 64 else 1


if __name__ == "__main__":
    sys.exit(main())
