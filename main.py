import argparse
import asyncio
import os
import sys
import time
import zlib

import aiohttp

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from sniper import settings
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
    pruned = store.prune_missing("minecraft", keep)
    print(
        f"minecraft: {len(names) + len(hot):,} watch names "
        f"({added:,} new, {pruned:,} pruned), fast lane {len(hot)}"
    )
    if extras:
        added = store.add_names("minecraft", extras)
        print(f"minecraft: {added:,} extra names")
    print(f"shard {idx}/{cnt}, db {os.path.basename(DB_PATH)}")


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
        task = asyncio.create_task(
            runner.run(once=args.once, limit=args.limit, minutes=args.minutes)
        )
        try:
            await asyncio.gather(task)
        finally:
            await session.close()
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
    bad = [n for n in names if not valid_for("minecraft", n)]
    added = store.add_names("minecraft", good)
    print(f"added {added:,}/{len(good):,}")
    if bad:
        print(f"skipped invalid: {', '.join(bad)}")


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
    print("  cloud    : 20 parallel github shards, each with its own IP, "
          "so no single IP exceeds the pacing above")


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
