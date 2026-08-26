import base64
import hashlib
import json
import os
import time

from . import aeslite
from .blocklist import is_blocked

# the feed is pushed every few seconds, so it carries only what the panel
# actually draws; the hourly artifact fragment can afford the full log
FEED_EVENTS = 40
FRAGMENT_EVENTS = 300


def build_payload(store, shard_idx: int, event_limit: int = FRAGMENT_EVENTS) -> dict:
    conn = store.conn
    counts = {"total": 0, "free": 0, "taken": 0, "unknown": 0, "locked": 0}
    free = []
    last_checked = 0.0
    for name, avail, lc, ca in conn.execute(
        "SELECT name, available, last_checked, changed_at FROM names "
        "WHERE platform = 'minecraft'"
    ):
        # legacy rows can predate a blocklist update; never surface them
        if is_blocked(name):
            continue
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
            "SELECT ts, name, detail FROM events ORDER BY ts DESC LIMIT ?",
            (event_limit * 3,),
        )
        if not is_blocked(name)
    ][:event_limit]
    return {
        "shard": shard_idx,
        "generated": int(time.time()),
        "last_checked": int(last_checked),
        "counts": counts,
        "free": free,
        "events": events,
    }


def fingerprint(payload: dict) -> str:
    """What the panel would visibly change by. Deliberately ignores clocks
    and check counters so a quiet shard does not push every few seconds."""
    names = sorted(r["n"] for r in payload["free"])
    newest = payload["events"][0] if payload["events"] else {}
    seed = json.dumps(
        [names, payload["counts"]["free"], newest.get("ts"), newest.get("n")],
        separators=(",", ":"),
    )
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _seal(payload: dict, passphrase: str) -> str:
    salt = os.urandom(16)
    iv = os.urandom(16)
    key = aeslite.derive_key(passphrase, salt)
    ct = aeslite.encrypt_cbc(
        key, iv, json.dumps(payload, separators=(",", ":")).encode()
    )
    return base64.b64encode(salt + iv + ct).decode()


def _write(out_path: str, text: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)


def write_fragment(store, shard_idx: int, out_path: str, passphrase: str | None) -> str:
    """The artifact/Pages format: a JS file the panel can load as a script."""
    payload = build_payload(store, shard_idx)
    head = "window.SNIPER_DATA=window.SNIPER_DATA||{shards:{}};"
    slot = f'window.SNIPER_DATA.shards["{shard_idx}"]='
    if passphrase is None:
        body = json.dumps(payload)
    else:
        body = f'"{_seal(payload, passphrase)}"'
    _write(out_path, head + slot + body + ";\n")
    return "plain" if passphrase is None else "encrypted"


def write_feed(store, shard_idx: int, out_path: str, passphrase: str) -> str:
    """The live format: just the encrypted blob, so the panel can fetch it
    straight off a branch with no Pages build in the way. Returns the
    fingerprint of what was written."""
    payload = build_payload(store, shard_idx, FEED_EVENTS)
    _write(out_path, _seal(payload, passphrase) + "\n")
    return fingerprint(payload)


def peek_fingerprint(store, shard_idx: int) -> str:
    return fingerprint(build_payload(store, shard_idx, FEED_EVENTS))
