"""Checks the live panel feed from the command line - the same blobs the
browser reads, decrypted with the same passphrase.

  PANEL_PASS=... python _verify_panel.py

Reports per-shard freshness so a dead shard is obvious: the panel only ever
shows what these branches contain.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, ".")
from sniper.aeslite import decrypt_cbc, derive_key

PASS = os.environ.get("PANEL_PASS", "")
if not PASS:
    sys.exit("set PANEL_PASS env var to the dashboard passphrase")

SLUG = os.environ.get("PANEL_REPO", "randomcharstohideprof/thetelehunter")
SHARDS = int(os.environ.get("SHARD_COUNT", "18"))
BLOB_RE = re.compile(r"^[A-Za-z0-9+/=]{64,}$")


def fetch(idx: int) -> str | None:
    url = (f"https://raw.githubusercontent.com/{SLUG}/feed-{idx}/frag.txt"
           f"?t={int(time.time())}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.read().decode().strip()
    except Exception as e:
        print(f"shard {idx:>2}: MISSING ({e})")
        return None


def rel(ts: float) -> str:
    d = max(0.0, time.time() - ts)
    if d < 90:
        return f"{d:.0f}s ago"
    if d < 5400:
        return f"{d / 60:.0f}m ago"
    return f"{d / 3600:.1f}h ago"


live = 0
tracked = 0
free_names: list[tuple[str, float]] = []
oldest = 0.0
for i in range(SHARDS):
    blob = fetch(i)
    if blob is None:
        continue
    if not BLOB_RE.match(blob):
        print(f"shard {i:>2}: MALFORMED (panel would ignore this)")
        continue
    raw = base64.b64decode(blob)
    try:
        payload = json.loads(
            decrypt_cbc(derive_key(PASS, raw[:16]), raw[16:32], raw[32:])
        )
    except Exception:
        print(f"shard {i:>2}: WRONG PASSPHRASE (or corrupt blob)")
        continue
    live += 1
    c = payload["counts"]
    tracked += c["total"]
    age = payload.get("last_checked") or payload.get("generated") or 0
    oldest = age if oldest == 0 else min(oldest, age)
    free_names += [(f["n"], f["c"]) for f in payload["free"]]
    print(f"shard {i:>2}: {c['total']:>5,} tracked  {c['free']:>3} claimable  "
          f"scanned {rel(age)}")

print(f"\ndecrypted shards: {live}/{SHARDS}  (passphrase OK)")
print(f"tracked names   : {tracked:,}")
print(f"claimable now   : {len(free_names)}")
if oldest:
    print(f"stalest shard   : scanned {rel(oldest)}")
if free_names:
    free_names.sort(key=lambda r: -r[1])
    print("newest finds    :",
          ", ".join(f"{n} ({rel(t)})" for n, t in free_names[:6]))
