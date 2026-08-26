import base64
import json
import re
import sys
import urllib.request

sys.path.insert(0, ".")
from sniper.aeslite import decrypt_cbc, derive_key

BASE = "https://randomcharstohideprof.github.io/thetelehunter/"

key = None
total_free = 0
total_tracked = 0
shards = 0
sample = []
for i in range(20):
    url = f"{BASE}shard_{i}.data.js"
    try:
        raw = urllib.request.urlopen(url, timeout=20).read().decode()
    except Exception as e:
        print(f"shard_{i}: MISSING ({e})")
        continue
    m = re.search(r'shards\["(\d+)"\]="([A-Za-z0-9+/=]+)"', raw)
    assert m, f"shard_{i}: no encrypted payload found"
    blob = base64.b64decode(m.group(2))
    salt, iv, ct = blob[:16], blob[16:32], blob[32:]
    payload = json.loads(decrypt_cbc(derive_key("8008", salt), iv, ct))
    c = payload["counts"]
    total_tracked += c["total"]
    total_free += c["free"]
    shards += 1
    for f in payload["free"][:2]:
        sample.append(f["n"])
print(f"decrypted shards: {shards}/20  (passphrase 8008 OK)")
print(f"tracked names   : {total_tracked:,}")
print(f"claimable now   : {total_free}")
if sample:
    print("sample finds    :", ", ".join(sample[:6]))
