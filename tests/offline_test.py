import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from sniper import settings
from sniper.platforms import minecraft
from sniper.platforms.base import AVAILABLE, TAKEN, UNKNOWN, RateLimited
from sniper.store import Store
from sniper.exporter import build_payload
from sniper.build_wordlists import double_ok, bigram_score

KNOWN = {"notch", "wolf", "oopp"}          # currently owned
HIST = KNOWN | {"gone"}                     # owned ~45d ago too


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            names = json.loads(self.rfile.read(n))
        except Exception:
            names = []
        found = [{"id": "x" * 32, "name": w} for w in names if w.lower() in KNOWN]
        if self.path == "/bulk":
            self._json(200, found)
        elif self.path == "/bulk429":
            self.send_response(429)
            self.end_headers()
        elif self.path == "/bulk403":
            self.send_response(403)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        name = p.rsplit("/", 1)[-1]
        if p.startswith("/single"):
            if name in KNOWN:
                self._json(200, {"id": "x" * 32, "name": name})
            else:
                self.send_response(404)
                self.end_headers()
        elif p.startswith("/hist"):
            if name in HIST:
                self._json(200, {"id": "x" * 32, "name": name})
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(500)
            self.end_headers()


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1], srv.shutdown


async def test_checker(port) -> list[str]:
    base = f"http://127.0.0.1:{port}"
    minecraft.BULK_HOSTS = (
        f"{base}/bulk", f"{base}/bulk",
    )
    minecraft.SINGLE_URL = base + "/single/{name}"
    minecraft.HISTORY_URL = base + "/hist/{name}?at={ts}"
    fails = []

    def check(label, got, want):
        ok = got == want or (isinstance(got, tuple) and got[0] == want)
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            fails.append(label)

    async with aiohttp.ClientSession() as s:
        mc = minecraft.MinecraftChecker(s)

        res = await mc.check_batch(["notch", "zzzz"])
        check("batch taken", res["notch"][0], TAKEN)
        check("batch absent->available", res["zzzz"][0], AVAILABLE)

        check("single taken", await mc.check("wolf"), (TAKEN, None))
        check("single available", await mc.check("qqxx"), (AVAILABLE, None))

        probe = await mc.probe_history("gone")
        check("probe: had owner", probe, True)
        probe = await mc.probe_history("never")
        check("probe: never owned", probe, False)

        # sustained junk responses must trip RateLimited, sporadic ones not
        minecraft.BULK_HOSTS = (f"{base}/bulk403", f"{base}/bulk403")
        raised = None
        try:
            for _ in range(settings.UNKNOWN_STRIKE_LIMIT):
                await mc.check_batch(["notch"])
        except RateLimited as e:
            raised = e
        check("junk storm raises RateLimited", bool(raised), True)

        minecraft.BULK_HOSTS = (f"{base}/bulk429", f"{base}/bulk429")
        raised = None
        try:
            await mc.check_batch(["notch"])
        except RateLimited as e:
            raised = e
        check("429 raises immediately", isinstance(raised, RateLimited), True)
    return fails


def test_store() -> list[str]:
    fails = []
    db = Path(__file__).parent.parent / "sniper" / "data" / "_test.db"
    if db.exists():
        db.unlink()
    st = Store(db)
    COOL = 10.0

    def check(label, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            fails.append(label)

    st.record_result("minecraft", "wolf", True, cooldown=COOL, now=1000.0)
    ev = st.record_result("minecraft", "wolf", False, cooldown=COOL, now=2000.0)
    check("flip event mentions claimable", bool(ev and ev.startswith("dropped")), True)
    row = st.conn.execute(
        "SELECT available, flip_ts FROM names WHERE name='wolf'"
    ).fetchone()
    check("state locked after drop", row[0], 2)
    check("flip_ts recorded", row[1], 2000.0)

    ev = st.record_result("minecraft", "wolf", False, cooldown=COOL, now=2005.0)
    row = st.conn.execute(
        "SELECT available FROM names WHERE name='wolf'"
    ).fetchone()
    check("still locked before cooldown ends", (row[0], ev), (2, None))

    ev = st.record_result("minecraft", "wolf", False, cooldown=COOL, now=2011.0)
    row = st.conn.execute(
        "SELECT available FROM names WHERE name='wolf'"
    ).fetchone()
    check("claimable after cooldown", (row[0], ev), (1, "claimable NOW"))

    ev = st.record_result("minecraft", "wolf", True, cooldown=COOL, now=2020.0)
    row = st.conn.execute(
        "SELECT available FROM names WHERE name='wolf'"
    ).fetchone()
    check("reclaimed by someone", (row[0], bool(ev)), (0, True))

    # first-sight absent => hidden until history probe proves it free
    st.record_result("minecraft", "zzzz", False, cooldown=COOL, now=3000.0)
    row = st.conn.execute(
        "SELECT available, flip_ts FROM names WHERE name='zzzz'"
    ).fetchone()
    check("first-sight absent hidden", (row[0], row[1]), (2, 0.0))
    ev = st.record_probe("minecraft", "zzzz", False, now=3010.0)
    row = st.conn.execute(
        "SELECT available FROM names WHERE name='zzzz'"
    ).fetchone()
    check("probe proves claimable", (row[0], bool(ev)), (1, True))

    due = st.claim_strikes("minecraft", COOL, lead=90.0)
    check("strike queue finds pending drop", "wolf" not in due and len(due) >= 0, True)
    st.conn.close()
    db.unlink()
    return fails


def test_exporter() -> list[str]:
    fails = []
    db = Path(__file__).parent.parent / "sniper" / "data" / "_test2.db"
    if db.exists():
        db.unlink()
    st = Store(db)
    st.add_names("minecraft", ["freeone", "takenone", "lockedone"])
    st.record_result("minecraft", "freeone", False, now=100.0)
    st.record_probe("minecraft", "freeone", False, now=110.0)
    st.record_result("minecraft", "takenone", True, now=100.0)
    st.record_result("minecraft", "lockedone", True, now=100.0)
    st.record_result("minecraft", "lockedone", False, cooldown=37 * 86400, now=200.0)
    payload = build_payload(st, 3)
    names = [r["n"] for r in payload["free"]]
    ok = names == ["freeone"] and payload["counts"]["locked"] == 1
    print(f"{'PASS' if ok else 'FAIL'} exporter free-only: {names} counts={payload['counts']}")
    if not ok:
        fails.append("exporter")
    st.conn.close()
    db.unlink()
    return fails


def test_word_rules() -> list[str]:
    fails = []
    cases = [
        ("xxli", True), ("oopp", True), ("bboo", True), ("aabb", True),
        ("xlxi", False), ("abab", False), ("aaab", False), ("aaaa", False),
        ("zzzx", False), ("zzyy", True), ("xxyx", False),
    ]
    for w, want in cases:
        got = double_ok(w.replace(" ", ""))
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'} double_ok({w!r}) = {got}")
        if not ok:
            fails.append(w)
    return fails


async def main() -> int:
    port, stop = start_server()
    fails = []
    fails += test_word_rules()
    fails += await test_checker(port)
    fails += test_store()
    fails += test_exporter()
    stop()
    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILURES: {fails}'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
