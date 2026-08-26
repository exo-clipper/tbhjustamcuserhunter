"""Builds a throwaway local copy of the panel plus real encrypted feed blobs,
so the render path can be driven in a browser without github or a live run.

  python _paneltest.py           # build ./_paneltest/
  python _paneltest.py --bump    # add one fresh find to shard 0 (tests NEW badge)

then open http://localhost:8765/index.html?feed=./ and unlock with the fixture
key printed on build (PANEL_TEST_PASS overrides it). Never the real passphrase:
this writes plain files into a working directory.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sniper import exporter
from sniper.store import Store

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_paneltest")
# not a credential: it encrypts made-up fixture data written into a working
# directory. Never put the real passphrase here.
FIXTURE_KEY = os.environ.get("PANEL_TEST_PASS") or "fixture-only-not-a-secret"

# shard -> (claimable, taken, unknown, locked); blocked names are planted on
# purpose so the export filter can be seen working in the browser
FIXTURE = {
    0: dict(free=["zelda", "wolf", "onyx"], taken=["notch", "dream"],
            unknown=["quix"], locked=["kelp"], blocked=["shag", "tits"]),
    1: dict(free=["luna"], taken=["herobrine"], unknown=[], locked=[],
            blocked=["orgy"]),
    2: dict(free=[], taken=["steve", "alex"], unknown=["zzab"], locked=[],
            blocked=[]),
}


def seed(path: str, spec: dict, now: float) -> Store:
    store = Store(path)
    plan = [(n, 1) for n in spec["free"]] + [(n, 0) for n in spec["taken"]] + \
           [(n, -1) for n in spec["unknown"]] + [(n, 2) for n in spec["locked"]] + \
           [(n, 1) for n in spec["blocked"]]
    store.add_names("minecraft", [n for n, _ in plan])
    for i, (name, avail) in enumerate(plan):
        store.conn.execute(
            "UPDATE names SET available = ?, last_checked = ?, changed_at = ? "
            "WHERE platform = 'minecraft' AND name = ?",
            (avail, now - 4, now - 30 * i, name),
        )
        if avail == 1:
            store.log_event("minecraft", name, "claimable (verified via history)")
        elif avail == 2:
            store.log_event("minecraft", name, "gone (owner dropped it)")
    store.conn.commit()
    return store


def main() -> None:
    bump = "--bump" in sys.argv
    now = time.time()
    if not bump:
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    shutil.copyfile(os.path.join("docs", "index.html"),
                    os.path.join(OUT, "index.html"))

    for idx, spec in FIXTURE.items():
        db = os.path.join(OUT, f"s{idx}.db")
        if bump and idx == 0:
            spec = dict(spec, free=spec["free"] + ["ghst"])
        if bump and os.path.exists(db):
            os.remove(db)
        store = seed(db, spec, now)
        blob = os.path.join(OUT, f"feed-{idx}", "frag.txt")
        fp = exporter.write_feed(store, idx, blob, FIXTURE_KEY)
        payload = exporter.build_payload(store, idx, exporter.FEED_EVENTS)
        store.conn.close()
        print(f"feed-{idx}: {os.path.getsize(blob)}B fp={fp} "
              f"free={[r['n'] for r in payload['free']]} "
              f"counts={payload['counts']}")
    print(f"\nserved from {OUT}; unlock with {FIXTURE_KEY!r}")


if __name__ == "__main__":
    main()
