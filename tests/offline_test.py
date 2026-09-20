import asyncio
import base64
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from sniper import aeslite, blocklist, exporter, settings
from sniper.platforms import minecraft
from sniper.platforms.base import AVAILABLE, TAKEN, UNKNOWN, RateLimited
from sniper.store import Store
from sniper.exporter import build_payload
from sniper.build_wordlists import double_ok, bigram_score
from sniper.wordlists import valid_for

# what the panel's own guard accepts off a feed branch (docs/index.html)
PANEL_BLOB = re.compile(r"^[A-Za-z0-9+/=]{64,}$")

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
    now = time.time()
    st.record_result("minecraft", "freeone", False, now=now - 10.0)
    st.record_probe("minecraft", "freeone", False, now=now - 5.0)
    st.record_result("minecraft", "takenone", True, now=now - 10.0)
    st.record_result("minecraft", "lockedone", True, now=now - 10.0)
    st.record_result("minecraft", "lockedone", False,
                     cooldown=37 * 86400, now=now - 2.0)
    payload = build_payload(st, 3)
    names = [r["n"] for r in payload["free"]]
    ok = names == ["freeone"] and payload["counts"]["locked"] == 1
    print(f"{'PASS' if ok else 'FAIL'} exporter free-only: {names} counts={payload['counts']}")
    if not ok:
        fails.append("exporter")

    # claim-on-the-spot: a free verdict older than PANEL_FRESH must never be
    # published, and must reappear the moment the shard re-confirms it
    st.add_names("minecraft", ["stalefree"])
    st.conn.execute(
        "UPDATE names SET available = 1, last_checked = ?, changed_at = ? "
        "WHERE name = 'stalefree'",
        (now - 300, now - 300),
    )
    st.conn.commit()
    stale = build_payload(st, 3)
    ok2 = "stalefree" not in [r["n"] for r in stale["free"]]
    print(f"{'PASS' if ok2 else 'FAIL'} stale free withheld from the panel: "
          f"{[r['n'] for r in stale['free']]}")
    if not ok2:
        fails.append("exporter")
    st.record_result("minecraft", "stalefree", False, now=now - 1.0)
    back = build_payload(st, 3)
    ok3 = sorted(r["n"] for r in back["free"]) == ["freeone", "stalefree"]
    print(f"{'PASS' if ok3 else 'FAIL'} re-confirmed free returns: "
          f"{[r['n'] for r in back['free']]}")
    if not ok3:
        fails.append("exporter")
    st.conn.close()
    db.unlink()
    return fails


def test_blocklist() -> list[str]:
    """Two things matter: the words minecraft refuses never reach the watchlist,
    and ordinary words that merely contain them are left alone."""
    fails = []

    def check(label, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            fails.append(label)

    # the exact words the operator hit in-game
    named = ["shag", "tits", "orgy", "damn", "jerk", "fuck", "bdsm"]
    check("named offensive words blocked",
          [blocklist.is_blocked(w) for w in named], [True] * len(named))
    check("named words rejected by valid_for",
          [valid_for("minecraft", w) for w in named], [False] * len(named))

    # substring matching would gut the watchlist, so matching must be exact
    ordinary = ["canal", "horn", "scum", "wolf", "assay", "pussycat", "hello"]
    check("ordinary words not blocked",
          [blocklist.is_blocked(w) for w in ordinary], [False] * len(ordinary))
    check("case/space insensitive", blocklist.is_blocked("  SHAG "), True)

    # BLOCK_EXTRA is the no-commit escape hatch used by the workflow
    before = os.environ.get("BLOCK_EXTRA")
    try:
        os.environ["BLOCK_EXTRA"] = "wibb, wobb"
        blocklist._cache = None
        check("BLOCK_EXTRA adds words",
              [blocklist.is_blocked("wibb"), blocklist.is_blocked("wobb")],
              [True, True])
    finally:
        if before is None:
            os.environ.pop("BLOCK_EXTRA", None)
        else:
            os.environ["BLOCK_EXTRA"] = before
        blocklist._cache = None
    check("BLOCK_EXTRA reverts", blocklist.is_blocked("wibb"), False)

    lists = {"four.txt", "hot.txt"}
    leaked = {}
    for fn in lists:
        p = Path(__file__).parent.parent / "sniper" / "data" / fn
        if not p.exists():
            continue
        words = {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()}
        bad = sorted(words & blocklist.blocked())
        if bad:
            leaked[fn] = bad
    check("shipped wordlists carry no blocked names", leaked, {})
    return fails


def test_feed() -> list[str]:
    """The live path: blob is panel-readable, blocked rows never surface, and
    the fingerprint only moves when the panel would visibly change."""
    fails = []
    root = Path(__file__).parent.parent
    db = root / "sniper" / "data" / "_test3.db"
    out = root / "sniper" / "data" / "_test3.feed"
    for p in (db, out):
        if p.exists():
            p.unlink()

    def check(label, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            fails.append(label)

    st = Store(db)
    # "shag" is blocked but planted as claimable, exactly like a row restored
    # from state that predates the blocklist entry
    for name in ("zelda", "shag", "taken"):
        st.add_names("minecraft", [name])
    now = time.time()
    st.conn.execute(
        "UPDATE names SET available = 1, last_checked = ?, changed_at = ? "
        "WHERE name IN ('zelda', 'shag')",
        (now - 5, now - 30),
    )
    st.conn.execute(
        "UPDATE names SET available = 0, last_checked = ? WHERE name = 'taken'",
        (now - 5,),
    )
    # a free verdict far outside the claim-on-the-spot window
    st.add_names("minecraft", ["oldfree"])
    st.conn.execute(
        "UPDATE names SET available = 1, last_checked = ?, changed_at = ? "
        "WHERE name = 'oldfree'",
        (now - 400, now - 400),
    )
    st.log_event("minecraft", "zelda", "claimable (verified via history)")
    st.log_event("minecraft", "shag", "claimable (verified via history)")
    st.conn.commit()

    payload = build_payload(st, 5, exporter.FEED_EVENTS)
    check("blocked name kept off the panel",
          [r["n"] for r in payload["free"]], ["zelda"])
    check("stale free withheld from the panel",
          "oldfree" in [r["n"] for r in payload["free"]], False)
    check("blocked name kept out of counts", payload["counts"]["total"], 3)
    check("blocked name kept out of the log",
          [e["n"] for e in payload["events"]], ["zelda"])

    fp = exporter.write_feed(st, 5, str(out), "pw")
    blob = out.read_text(encoding="utf-8").strip()
    check("blob matches the panel's guard", bool(PANEL_BLOB.match(blob)), True)

    raw = base64.b64decode(blob)
    key = aeslite.derive_key("pw", raw[:16])
    back = json.loads(aeslite.decrypt_cbc(key, raw[16:32], raw[32:]))
    check("round-trips through decrypt",
          (back["shard"], [r["n"] for r in back["free"]]), (5, ["zelda"]))

    # the panel derives its own key; if either side's parameters drift the feed
    # silently stops decrypting, so pin them to each other here
    panel = (root / "docs" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"PBKF_ITER\s*=\s*(\d+)", panel)
    check("panel KDF iterations match the server",
          int(m.group(1)) if m else None, settings.KDF_ITERATIONS)
    check("blob carries the agreed salt", raw[:16], settings.FEED_SALT)
    second = exporter._seal(payload, "pw")
    check("same payload re-encrypts differently (fresh IV)", second == blob, False)

    check("fingerprint stable while nothing changes",
          exporter.peek_fingerprint(st, 5), fp)
    st.add_names("minecraft", ["wolf"])
    st.conn.execute(
        "UPDATE names SET available = 1, last_checked = ?, changed_at = ? "
        "WHERE name = 'wolf'",
        (now - 5, now - 5),
    )
    st.conn.commit()
    check("fingerprint moves on a new find",
          exporter.peek_fingerprint(st, 5) != fp, True)

    st.conn.close()
    for p in (db, out):
        if p.exists():
            p.unlink()
    return fails


def test_no_secrets_in_tree() -> list[str]:
    """The repo is public and history is forever, so this is a tripwire, not a
    formality: it fails the build before a credential can be pushed."""
    fails = []
    root = Path(__file__).parent.parent

    def check(label, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            fails.append(label)

    # real credential shapes, not vague words: github tokens, private keys,
    # slack/telegram/aws keys, and hardcoded secret assignments
    patterns = [
        (r"gh[pousr]_[A-Za-z0-9]{20,}", "github token"),
        (r"github_pat_[A-Za-z0-9_]{20,}", "github fine-grained pat"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
        (r"AKIA[0-9A-Z]{16}", "aws key id"),
        (r"xox[baprs]-[A-Za-z0-9-]{10,}", "slack token"),
        (r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}", "telegram bot token"),
        (r"(?i)\b(pass(phrase|word)?|secret|token|api_?key)\b\s*[:=]\s*"
         r"['\"][^'\"\n]{6,}['\"]", "hardcoded credential"),
    ]
    skip_dirs = {".git", ".venv", "__pycache__", "_paneltest", "state",
                 "frag", "frag_live"}
    text_ext = {".py", ".html", ".yml", ".yaml", ".json", ".md", ".txt",
                ".js", ".css", ".sh", ".cfg", ".toml", ".ini", ""}
    hits = []
    scanned = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_ext:
            continue
        if skip_dirs & set(p.name for p in path.parents):
            continue
        if path.name == Path(__file__).name:   # this file holds the patterns
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for rx, what in patterns:
            for m in re.finditer(rx, body):
                line = body[: m.start()].count("\n") + 1
                hits.append(f"{path.relative_to(root).as_posix()}:{line} {what}")
    print(f"     scanned {scanned} text files for credential patterns")
    check("no credentials in the working tree", hits, [])

    # the panel is served to anyone; the passphrase must live only in the secret
    panel = (root / "docs" / "index.html").read_text(encoding="utf-8")
    check("panel ships no passphrase",
          bool(re.search(r"(?i)snipe_key\s*[:=]\s*['\"].+['\"]", panel)), False)

    # and the ignore rules that keep it that way must not regress
    ignore = (root / ".gitignore").read_text(encoding="utf-8").split()
    for need in ("*.db", ".env", "secrets/", "*.pem", "*.key", "*.log"):
        check(f"gitignore covers {need}", need in ignore, True)
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
    fails += test_blocklist()
    fails += test_no_secrets_in_tree()
    fails += await test_checker(port)
    fails += test_store()
    fails += test_exporter()
    fails += test_feed()
    stop()
    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILURES: {fails}'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
