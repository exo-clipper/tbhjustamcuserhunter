import argparse
import asyncio
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import aiohttp

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from sniper import blocklist, settings
from sniper.engine import GREEN, PlatformRunner
from sniper.platforms import CHECKERS
from sniper.platforms.base import RateLimited
from sniper.store import Store
from sniper.wordlists import load_hot, load_names, valid_for
from sniper import exporter

DB_PATH = os.environ.get(
    "SNIPE_DB", os.path.join(ROOT, "sniper", "data", "sniper.db")
)


def _shard() -> tuple[int, int]:
    try:
        idx = int(os.environ.get("SHARD_INDEX", "0"))
        cnt = int(os.environ.get("SHARD_COUNT", "1"))
    except ValueError:
        return 0, 1
    return max(0, idx), max(1, cnt)


def _extra_names() -> list[str]:
    raw = os.environ.get("EXTRA_NAMES", "").replace("\n", ",")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _shard_filter(names: list[str], idx: int, cnt: int) -> list[str]:
    if cnt <= 1:
        return names
    return [n for n in names if zlib.crc32(n.encode()) % cnt == idx]


def cmd_init(args) -> None:
    store = Store(DB_PATH)
    idx, cnt = _shard()
    # fresh-platform hygiene: drop anything not minecraft (e.g. restored
    # state from the telegram era) and its stale event log
    store.conn.execute(
        "DELETE FROM names WHERE platform != 'minecraft'"
    )
    store.conn.execute(
        "DELETE FROM events WHERE platform != 'minecraft'"
    )
    store.conn.commit()
    names = _shard_filter(load_names("minecraft"), idx, cnt)
    hot = load_hot(idx, cnt)
    added = store.add_names("minecraft", names + [n for n in hot if n not in set(names)])
    extras = [n for n in _extra_names() if valid_for("minecraft", n)]
    keep = set(names) | set(hot) | set(extras)
    # keep never contains a blocked name (valid_for rejects them), so restored
    # state carrying words a newer blocklist covers gets swept out here
    pruned = store.prune_missing("minecraft", keep)
    print(
        f"minecraft: {len(names) + len(hot):,} watch names "
        f"({added:,} new, {pruned:,} pruned), fast lane {len(hot)}"
    )
    if extras:
        added = store.add_names("minecraft", extras)
        print(f"minecraft: {added:,} extra names")
    print(f"shard {idx}/{cnt}, db {os.path.basename(DB_PATH)}")


def _git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd)


def _redact(text: str) -> str:
    """Actions logs on a public repo are world-readable and git happily quotes
    the remote URL back at you in error messages. That URL carries the push
    token, so nothing from a subprocess gets printed unfiltered - GitHub's own
    secret masking is a nice backstop, not something to depend on."""
    out = re.sub(r"(https?://)[^\s/@]*:[^\s/@]*@", r"\1***:***@", text)
    for var in ("GH_TOKEN", "GITHUB_TOKEN", "DASH_PASSPHRASE"):
        val = os.environ.get(var, "").strip()
        if len(val) > 3:
            out = out.replace(val, "***")
    return out


def _feed_remote() -> str:
    """Where feed branches are pushed. FEED_REMOTE exists so the push path
    can be exercised against a local bare repo in tests."""
    override = os.environ.get("FEED_REMOTE", "")
    if override:
        return override
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not slug or not token:
        return ""
    return f"https://x-access-token:{token}@github.com/{slug}.git"


def push_feed(blob_path: str, idx: int) -> bool:
    """Force-push this shard's blob onto its own `feed-N` branch so the panel
    sees it within seconds instead of waiting for a Pages build.

    Done in a throwaway repo, never in the runner's checkout: switching
    branches in-place would delete main.py and sniper/ out from under the
    watcher that is running. One branch per shard means the push is always a
    force-push of a single fresh commit, so 18 shards never race each other.
    """
    url = _feed_remote()
    if not url:
        return False
    branch = settings.FEED_BRANCH.format(idx=idx)
    ident = [
        "-c", "user.name=sniper-bot",
        "-c", "user.email=sniper-bot@users.noreply.github.com",
    ]
    for attempt in range(3):
        work = tempfile.mkdtemp(prefix=f"feed{idx}_")
        try:
            if _git(["init", "-q", "-b", branch], cwd=work).returncode != 0:
                continue
            shutil.copyfile(blob_path, os.path.join(work, settings.FEED_FILE))
            _git(["add", settings.FEED_FILE], cwd=work)
            if _git(ident + ["commit", "-q", "-m", f"feed {idx}"], cwd=work).returncode != 0:
                continue
            push = _git(["push", "--force", url, f"HEAD:refs/heads/{branch}"], cwd=work)
            if push.returncode == 0:
                return True
            if attempt == 2:
                print(f"[flush] shard {idx}: push failed: "
                      f"{_redact(push.stderr.strip())[-200:]}", flush=True)
        except OSError as e:
            print(f"[flush] shard {idx}: {_redact(str(e))}", flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        time.sleep(2.0 + random.random() * 3.0)
    return False


async def flusher_task(runner: PlatformRunner, store: Store, idx: int) -> None:
    """Publish this shard's findings continuously: the moment the visible
    picture changes, plus a heartbeat so the panel's "last scan" stays true."""
    passphrase = os.environ.get("DASH_PASSPHRASE", "").strip()
    if not passphrase:
        print("[flush] DASH_PASSPHRASE unset; live panel feed disabled", flush=True)
        return
    offset = (idx % 8) * settings.STAGGER_PER_SHARD
    out = os.path.join(ROOT, "frag_live", f"shard_{idx}.data")
    last_print = ""
    sent_fp = None
    last_push = 0.0
    await asyncio.sleep(settings.FLUSH_FIRST_DELAY + offset)
    while not runner.stopping():
        try:
            since = time.monotonic() - last_push
            fp = exporter.peek_fingerprint(store, idx)
            due = (fp != sent_fp and since >= settings.FLUSH_MIN_GAP) or \
                  since >= settings.FLUSH_HEARTBEAT
            if not due:
                await asyncio.sleep(settings.FLUSH_POLL)
                continue
            fp = exporter.write_feed(store, idx, out, passphrase)
            ok = await asyncio.get_running_loop().run_in_executor(
                None, push_feed, out, idx
            )
            last_push = time.monotonic()
            if ok:
                sent_fp = fp
                line = f"[flush] shard {idx}: live ({runner.found_free} claimable)"
                if line != last_print:
                    print(line, flush=True)
                    last_print = line
            else:
                await asyncio.sleep(20)
        except Exception as e:
            print(f"[flush] shard {idx}: {e}", flush=True)
            await asyncio.sleep(30)


def flush_once(store: Store, idx: int) -> bool:
    """Write and push this shard's feed right now (used as the parting shot
    when a cycle ends, so the branch holds the final state of the run)."""
    passphrase = os.environ.get("DASH_PASSPHRASE", "").strip()
    if not passphrase:
        return False
    out = os.path.join(ROOT, "frag_live", f"shard_{idx}.data")
    exporter.write_feed(store, idx, out, passphrase)
    return push_feed(out, idx)


def cmd_run(args) -> None:
    store = Store(DB_PATH)
    idx, cnt = _shard()

    async def _go():
        session = aiohttp.ClientSession(
            headers={
                "User-Agent": settings.USER_AGENT,
                "Accept": "application/json",
            }
        )
        runner = PlatformRunner(
            store,
            CHECKERS["minecraft"](session),
            delay=args.delay,
            quiet=args.quiet,
        )
        runner.set_hot(load_hot(idx, cnt))
        tasks = [asyncio.create_task(
            runner.run(once=args.once, limit=args.limit, minutes=args.minutes)
        )]
        if not args.no_flush:
            tasks.append(asyncio.create_task(flusher_task(runner, store, idx)))
        try:
            await asyncio.gather(*tasks)
        finally:
            await session.close()
            if not args.no_flush:
                flush_once(store, idx)
            store.conn.close()
            print(
                f"[minecraft] checked {runner.checked}, found claimable {runner.found_free}"
            )

    try:
        asyncio.run(_go())
    except KeyboardInterrupt:
        print("\nstopped; progress saved")
    else:
        print("done")


def cmd_stats(args) -> None:
    store = Store(DB_PATH)
    counts = store.stats().get("minecraft", {})
    labels = {-1: "unknown", 0: "taken", 1: "claimable", 2: "locked"}
    total = sum(counts.values())
    parts = ", ".join(f"{labels.get(k, k)}={v:,}" for k, v in sorted(counts.items()))
    print(f"minecraft: {total:,} tracked | {parts}")
    rows = store.conn.execute(
        "SELECT ts, platform, name FROM events ORDER BY ts DESC LIMIT ?",
        (args.last,),
    ).fetchall()
    if rows:
        print(f"\nlast {len(rows)} events:")
        for ts, plat, name in rows:
            print(f"  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))} {plat} {name}")


def cmd_free(args) -> None:
    store = Store(DB_PATH)
    found = store.free_names("minecraft")
    print(f"minecraft: {len(found):,} claimable now")
    for name, ts in found[: args.top]:
        when = time.strftime("%m-%d %H:%M", time.localtime(ts))
        print(f"  {name} (free since {when})")


def cmd_add(args) -> None:
    store = Store(DB_PATH)
    names = [n.strip().lower() for n in args.names]
    good = [n for n in names if valid_for("minecraft", n)]
    blocked = [n for n in names if blocklist.is_blocked(n)]
    bad = [n for n in names if n not in good and n not in blocked]
    added = store.add_names("minecraft", good)
    print(f"added {added:,}/{len(good):,}")
    if blocked:
        print(f"skipped (minecraft rejects these): {', '.join(blocked)}")
    if bad:
        print(f"skipped invalid: {', '.join(bad)}")


def cmd_block(args) -> None:
    """Teach the radar that minecraft refuses a name, and drop it everywhere."""
    names = [n.strip().lower() for n in args.names]
    fresh = blocklist.add(names)
    store = Store(DB_PATH)
    removed = store.remove_names("minecraft", names)
    store.conn.close()
    if fresh:
        print(f"blocked {len(fresh)}: {', '.join(fresh)}")
    else:
        print("already blocked; nothing added")
    print(f"removed from this db: {removed:,}")
    print("commit sniper/data/blocked.txt to apply it in the cloud, or add the "
          "same words to the BLOCK_EXTRA secret for an instant effect")


def cmd_remove(args) -> None:
    store = Store(DB_PATH)
    names = [n.strip().lower() for n in args.names]
    removed = store.remove_names("minecraft", names)
    print(f"removed {removed:,}")


def cmd_test(args) -> None:
    names = [n.strip().lower() for n in args.names]

    async def _go():
        conn = aiohttp.ClientSession(
            headers={"User-Agent": settings.USER_AGENT, "Accept": "application/json"}
        )
        checker = CHECKERS["minecraft"](conn)
        try:
            for i, name in enumerate(names):
                if i:
                    await asyncio.sleep(checker.DEFAULT_DELAY)
                try:
                    verdict, note = await checker.check(name)
                except RateLimited as e:
                    print(f"{name}: RATE-LIMITED ({e})", flush=True)
                    continue
                color = GREEN if verdict == "available" else "\033[0m"
                suffix = f" ({note})" if note else ""
                print(f"{color}{name}: {verdict}\033[0m{suffix}".rstrip(), flush=True)
        finally:
            await conn.close()

    asyncio.run(_go())


def cmd_export(args) -> None:
    idx, _cnt = _shard()
    out = args.out or os.path.join(ROOT, "docs", f"shard_{idx}.data.js")
    passphrase = os.environ.get("DASH_PASSPHRASE", "").strip() or None
    if passphrase is None and not args.plain:
        print("DASH_PASSPHRASE not set; refusing to write findings in plaintext "
              "(pass --plain only for local debugging)")
        sys.exit(2)
    store = Store(DB_PATH)
    try:
        mode = exporter.write_fragment(store, idx, out, passphrase)
    finally:
        store.conn.close()
    print(f"wrote {mode} fragment -> {out}")


def cmd_pace(_args) -> None:
    print("safety pacing:")
    print(f"  minecraft: batches of {settings.BATCH_SIZE}, 1 POST every "
          f"~{settings.BATCH_DELAY}s per IP (+/-{int(settings.JITTER * 100)}% jitter) "
          f"= ~{settings.BATCH_SIZE / settings.BATCH_DELAY:.0f} names/s per shard")
    print(f"  sweep    : every name at least every {settings.SWEEP_INTERVAL:.0f}s; "
          f"fast lane every {settings.HOT_RECHECK:.0f}s; free re-check every "
          f"{settings.FREE_RECHECK // 60}min")
    print(f"  lifecycle: dropped names locked {settings.COOLDOWN // 86400} days; "
          f"strike window starts {settings.STRIKE_LEAD:.0f}s before unlock")
    print(f"  breaker  : {settings.BREAKER_THRESHOLD} throttle signals -> pause "
          f"(starts {settings.BREAKER_START // 60}min, doubles each trip, "
          f"max {settings.BREAKER_MAX // 3600}h); "
          f"{settings.UNKNOWN_STRIKE_LIMIT} junk responses also count as one signal")
    print(f"  cloud    : {_shard()[1]} parallel github shards, each with its own "
          "IP, so no single IP exceeds the pacing above")
    print(f"  panel    : each shard force-pushes branch "
          f"{settings.FEED_BRANCH.format(idx='N')} the moment its finds change "
          f"(min {settings.FLUSH_MIN_GAP:.0f}s apart), heartbeat every "
          f"{settings.FLUSH_HEARTBEAT / 60:.0f}min; no Pages build in the path")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="main.py",
        description="Watch minecraft for readable 4-letter usernames becoming claimable.",
        epilog="examples:\n"
               "  python main.py init\n"
               "  python main.py run\n"
               "  python main.py run --minutes 45 --quiet --delay 1.2\n"
               "  python main.py test zelda wolf\n"
               "  python main.py add mycoolname\n"
               "  python main.py free --top 50\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="load wordlists into the database")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("run", help="start monitoring")
    p.add_argument("--once", action="store_true", help="exit when everything due is checked once")
    p.add_argument("--limit", type=int, default=None, help="stop after N checks")
    p.add_argument("--minutes", type=float, default=None,
                   help="stop after this many minutes (for CI runs)")
    p.add_argument("--quiet", action="store_true", help="only print finds")
    p.add_argument("--no-flush", action="store_true",
                   help="disable live fragment pushes (for local testing)")
    p.add_argument("--delay", type=float, default=settings.BATCH_DELAY,
                   help="seconds between batch POSTs (default %(default)s)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("stats", help="database summary + recent events")
    p.add_argument("--last", type=int, default=15)
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("free", help="list currently-claimable usernames")
    p.add_argument("--top", type=int, default=25)
    p.set_defaults(fn=cmd_free)

    p = sub.add_parser("add", help="add custom usernames to watch")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", help="remove usernames from the watch list")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("block", help="mark names minecraft refuses, and drop them")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_block)

    p = sub.add_parser("test", help="check specific names right now (live request)")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_test)

    p = sub.add_parser("pace", help="show current safety pacing")
    p.set_defaults(fn=cmd_pace)

    p = sub.add_parser("export", help="write encrypted dashboard data fragment")
    p.add_argument("--out", default=None, help=argparse.SUPPRESS)
    p.add_argument("--plain", action="store_true",
                   help="write unencrypted json (local debugging only)")
    p.set_defaults(fn=cmd_export)

    return ap


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.fn(args)
