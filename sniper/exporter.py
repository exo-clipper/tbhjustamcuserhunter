import base64
import json
import os
import time

from . import aeslite


def build_payload(store, shard_idx: int) -> dict:
    conn = store.conn
    counts = {"total": 0, "free": 0, "taken": 0, "unknown": 0, "locked": 0}
    free = []
    last_checked = 0.0
    for name, avail, lc, ca in conn.execute(
        "SELECT name, available, last_checked, changed_at FROM names"
    ):
        counts["total"] += 1
        if lc > last_checked:
            last_checked = lc
        if avail == 1:
            counts["free"] += 1
            free.append({"n": name, "t": int(ca), "c": int(lc), "l": len(name)})
        elif avail == 0:
            counts["taken"] += 1
        elif avail == 2:
            counts["locked"] += 1
        else:
            counts["unknown"] += 1
    free.sort(key=lambda r: -r["t"])
    events = [
        {"ts": int(ts), "n": name, "m": detail}
        for ts, name, detail in conn.execute(
            "SELECT ts, name, detail FROM events ORDER BY ts DESC LIMIT 300"
        )
    ]
    return {
        "shard": shard_idx,
        "generated": int(time.time()),
        "last_checked": int(last_checked),
        "counts": counts,
        "free": free,
        "events": events,
    }


def write_fragment(store, shard_idx: int, out_path: str, passphrase: str | None) -> str:
    payload = build_payload(store, shard_idx)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("window.SNIPER_DATA=window.SNIPER_DATA||{shards:{}};")
        if passphrase is None:
            f.write(f'window.SNIPER_DATA.shards["{shard_idx}"]=')
            f.write(json.dumps(payload))
        else:
            salt = os.urandom(16)
            iv = os.urandom(16)
            key = aeslite.derive_key(passphrase, salt)
            ct = aeslite.encrypt_cbc(
                key, iv, json.dumps(payload, separators=(",", ":")).encode()
            )
            blob = base64.b64encode(salt + iv + ct).decode()
            f.write(f'window.SNIPER_DATA.shards["{shard_idx}"]="{blob}"')
        f.write(";\n")
    return "plain" if passphrase is None else "encrypted"
