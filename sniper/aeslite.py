_SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40]


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _expand_key(key: bytes) -> list:
    words = [list(key[i : i + 4]) for i in range(0, 32, 4)]
    for i in range(8, 60):
        temp = list(words[i - 1])
        if i % 8 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // 8 - 1]
        elif i % 8 == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - 8][j] ^ temp[j] for j in range(4)])
    return words


def _add_round_key(state: list, words: list, rnd: int) -> None:
    for col in range(4):
        w = words[rnd * 4 + col]
        for row in range(4):
            state[row + 4 * col] ^= w[row]


def _sub_bytes(state: list) -> None:
    for i in range(16):
        state[i] = _SBOX[state[i]]


def _shift_rows(state: list) -> None:
    for r in range(1, 4):
        row = [state[r + 4 * c] for c in range(4)]
        row = row[r:] + row[:r]
        for c in range(4):
            state[r + 4 * c] = row[c]


def _mix_columns(state: list) -> None:
    for c in range(4):
        a = [state[r + 4 * c] for r in range(4)]
        x = [_xtime(v) for v in a]
        state[0 + 4 * c] = x[0] ^ a[1] ^ x[1] ^ a[2] ^ a[3]
        state[1 + 4 * c] = a[0] ^ x[1] ^ a[2] ^ x[2] ^ a[3]
        state[2 + 4 * c] = a[0] ^ a[1] ^ x[2] ^ a[3] ^ x[3]
        state[3 + 4 * c] = x[0] ^ a[0] ^ a[1] ^ a[2] ^ x[3]


def encrypt_block(block: bytes, words: list) -> bytes:
    state = list(block)
    _add_round_key(state, words, 0)
    for rnd in range(1, 14):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, words, rnd)
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, words, 14)
    return bytes(state)


def pad(data: bytes) -> bytes:
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


def encrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    assert len(key) == 32 and len(iv) == 16
    words = _expand_key(key)
    data = pad(data)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i : i + 16], prev))
        prev = encrypt_block(block, words)
        out += prev
    return bytes(out)


def derive_key(passphrase: str, salt: bytes, iterations: int = 0) -> bytes:
    """Default work factor comes from settings so no call site can silently
    derive under the wrong one and write a blob the panel cannot open."""
    if not iterations:
        from .settings import KDF_ITERATIONS

        iterations = KDF_ITERATIONS
    return hashlib_pbkdf2(passphrase, salt, iterations)


_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _inv_xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    out = 0
    for _ in range(8):
        if b & 1:
            out ^= a
        a = _inv_xtime(a)
        b >>= 1
    return out


def _inv_shift_rows(state: list) -> None:
    for r in range(1, 4):
        row = [state[r + 4 * c] for c in range(4)]
        row = row[-r:] + row[:-r]
        for c in range(4):
            state[r + 4 * c] = row[c]


def _inv_sub_bytes(state: list) -> None:
    for i in range(16):
        state[i] = _INV_SBOX[state[i]]


def _inv_mix_columns(state: list) -> None:
    for c in range(4):
        a = [state[r + 4 * c] for r in range(4)]
        state[0 + 4 * c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
        state[1 + 4 * c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
        state[2 + 4 * c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
        state[3 + 4 * c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)


def decrypt_block(block: bytes, words: list) -> bytes:
    state = list(block)
    _add_round_key(state, words, 14)
    for rnd in range(13, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, words, rnd)
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, words, 0)
    return bytes(state)


def unpad(data: bytes) -> bytes:
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise ValueError("bad padding")
    return data[:-n]


def decrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    assert len(key) == 32 and len(iv) == 16 and len(data) % 16 == 0
    words = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i : i + 16]
        out += bytes(a ^ b for a, b in zip(decrypt_block(blk, words), prev))
        prev = blk
    return unpad(bytes(out))


def hashlib_pbkdf2(passphrase: str, salt: bytes, iterations: int) -> bytes:
    import hashlib

    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, iterations, dklen=32
    )
