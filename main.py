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
from sniper.wordlists import load_names, valid_for
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
    return [s.strip().lower().lstrip("@") for s in raw.split(",") if s.strip()]


def _shard_filter(names: list[str], idx: int, cnt: int) -> list[str]:
    if cnt <= 1:
        return names
    return [n for n in names if zlib.crc32(n.encode()) % cnt == idx]


def cmd_init(args) -> None:
    store = Store(DB_PATH)
    idx, cnt = _shard()
    names = _shard_filter(load_names("telegram"), idx, cnt)
    added = store.add_names("telegram", names)
    extras = [n for n in _extra_names() if valid_for("telegram", n)]
    keep = set(names) | set(extras)
    pruned = store.prune_missing("telegram", keep)
    print(f"telegram: {len(names):,} watch names ({added:,} new, {pruned:,} pruned)")
    if extras:
        added = store.add_names("telegram", extras)
        print(f"telegram: {added:,} extra names")
    print(f"shard {idx}/{cnt}, db {os.path.basename(DB_PATH)}")


def cmd_run(args) -> None:
    store = Store(DB_PATH)

    async def _go():
        session = aiohttp.ClientSession(
            headers={
                "User-Agent": settings.USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        runner = PlatformRunner(
            store,
            CHECKERS["telegram"](session),
            delay=args.tg_delay,
            quiet=args.quiet,
        )
        task = asyncio.create_task(
            runner.run(once=args.once, limit=args.limit, minutes=args.minutes)
        )
        try:
            await asyncio.gather(task)
        finally:
            await session.close()
            store.conn.close()
            print(f"[telegram] checked {runner.checked}, found free {runner.found_free}")

    try:
        asyncio.run(_go())
    except KeyboardInterrupt:
        print("\nstopped; progress saved")
    else:
        print("done")


def cmd_stats(args) -> None:
    store = Store(DB_PATH)
    counts = store.stats().get("telegram", {})
    labels = {-1: "unknown", 0: "taken", 1: "free"}
    total = sum(counts.values())
    parts = ", ".join(f"{labels.get(k, k)}={v:,}" for k, v in sorted(counts.items()))
    print(f"telegram: {total:,} tracked | {parts}")
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
    found = store.free_names("telegram")
    print(f"telegram: {len(found):,} currently free")
    for name, ts in found[: args.top]:
        when = time.strftime("%m-%d %H:%M", time.localtime(ts))
        print(f"  @{name} (seen free since {when})")


def cmd_add(args) -> None:
    store = Store(DB_PATH)
    names = [n.strip().lower().lstrip("@") for n in args.names]
    good = [n for n in names if valid_for("telegram", n)]
    bad = [n for n in names if not valid_for("telegram", n)]
    added = store.add_names("telegram", good)
    print(f"added {added:,}/{len(good):,}")
    if bad:
        print(f"skipped invalid: {', '.join(bad)}")


def cmd_remove(args) -> None:
    store = Store(DB_PATH)
    names = [n.strip().lower().lstrip("@") for n in args.names]
    removed = store.remove_names("telegram", names)
    print(f"removed {removed:,}")


def cmd_test(args) -> None:
    names = [n.strip().lower().lstrip("@") for n in args.names]

    async def _go():
        conn = aiohttp.ClientSession(
            headers={"User-Agent": settings.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        )
        checker = CHECKERS["telegram"](conn)
        try:
            for i, name in enumerate(names):
                if i:
                    await asyncio.sleep(checker.DEFAULT_DELAY)
                try:
                    verdict, note = await checker.check(name)
                except RateLimited as e:
                    print(f"@{name}: RATE-LIMITED ({e})", flush=True)
                    continue
                color = GREEN if verdict == "available" else "\033[0m"
                suffix = f" ({note})" if note else ""
                print(f"{color}@{name}: {verdict}\033[0m{suffix}".rstrip(), flush=True)
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
    print(f"  telegram : 1 check every ~{settings.TELEGRAM_DELAY}s per IP "
          f"(+/-{int(settings.JITTER * 100)}% jitter), re-check FREE every "
          f"{settings.FREE_RECHECK['telegram'] // 60}min")
    print(f"  breaker  : {settings.BREAKER_THRESHOLD} slow-down signals -> pause "
          f"(starts {settings.BREAKER_START['telegram'] // 60}min, doubles each trip, "
          f"max {settings.BREAKER_MAX // 3600}h)")
    print("  cloud    : 20 parallel github shards, each with its own IP, "
          "so no single IP exceeds the pacing above")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="main.py",
        description="Watch telegram for all 3-letter and readable 4-letter usernames becoming free.",
        epilog="examples:\n"
               "  python main.py init\n"
               "  python main.py run\n"
               "  python main.py run --minutes 12 --quiet --tg-delay 1.0\n"
               "  python main.py test murk zqvx\n"
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
                   help="stop after this many minutes (for CI/scheduled runs)")
    p.add_argument("--quiet", action="store_true", help="only print alerts")
    p.add_argument("--tg-delay", type=float, default=settings.TELEGRAM_DELAY,
                   help="seconds between checks (default %(default)s)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("stats", help="database summary + recent events")
    p.add_argument("--last", type=int, default=15)
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("free", help="list currently-free usernames")
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
