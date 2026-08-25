import asyncio
import random
import time
from pathlib import Path

from . import settings
from .notifier import fire_and_forget
from .platforms.base import AVAILABLE, TAKEN, UNKNOWN, CheckerDisabled, RateLimited

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"

DATA_DIR = Path(__file__).parent / "data"
ALERT_LOG = DATA_DIR / "alerts.log"


def alert(platform: str, name: str, length: int) -> None:
    line = f"*** {platform.upper()} @{name} IS FREE -> https://t.me/{name}"
    print(f"\n{GREEN}{line}{RESET}\a", flush=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    with open(DATA_DIR / f"free_{platform}.txt", "a", encoding="utf-8") as f:
        f.write(f"{name}\n")
    fire_and_forget(platform, name, length)


class PlatformRunner:
    def __init__(self, store, checker, delay=None, min_interval=None, quiet=False):
        self.store = store
        self.checker = checker
        platform = checker.NAME
        self.delay = delay if delay is not None else checker.DEFAULT_DELAY
        self.min_interval = (
            min_interval if min_interval is not None else settings.BASE_INTERVALS[platform]
        )
        self.free_interval = settings.FREE_RECHECK[platform]
        self.breaker_start = settings.BREAKER_START[platform]
        self.quiet = quiet
        self.checked = 0
        self.found_free = 0
        self._last_dispatch = 0.0
        self._stopped = asyncio.Event()
        self._idle_since: float | None = None
        self._strikes = 0
        self._level = 0
        self._cooldown_until = 0.0

    def _pace(self) -> float:
        now = time.monotonic()
        step = max(0.5, self.delay * (1.0 + random.uniform(-settings.JITTER, settings.JITTER)))
        wait = self._last_dispatch + step - now
        self._last_dispatch = max(now, self._last_dispatch + step)
        return max(wait, 0.0)

    def _trip_breaker(self, reason: str) -> None:
        cooldown = min(settings.BREAKER_MAX, self.breaker_start * (2**self._level))
        self._level += 1
        self._strikes = 0
        self._cooldown_until = time.monotonic() + cooldown
        mins = int(cooldown // 60)
        self.store.log_event(
            self.checker.NAME, "", f"breaker: paused {mins}m ({reason})"
        )
        print(
            f"{RED}[{self.checker.NAME}] possible rate limiting ({reason}) "
            f"-> pausing this platform for {mins} min{RESET}",
            flush=True,
        )

    async def _check_one(self, name: str) -> None:
        try:
            verdict, note = await self.checker.check(name)
        except RateLimited as e:
            self._strikes += 1
            self.store.log_event(self.checker.NAME, "", f"throttle: {e}")
            print(f"{YELLOW}[{self.checker.NAME}] {e}{RESET}", flush=True)
            if self._strikes >= settings.BREAKER_THRESHOLD:
                self._trip_breaker(str(e)[:60])
            return
        except CheckerDisabled as e:
            print(f"{RED}[{self.checker.NAME}] disabled: {e}{RESET}", flush=True)
            self._stopped.set()
            return
        if verdict in (AVAILABLE, TAKEN):
            self._strikes = 0
            self._level = 0
        transition, first_free = self.store.record(
            self.checker.NAME,
            name,
            verdict == AVAILABLE if verdict in (AVAILABLE, TAKEN) else None,
        )
        self.checked += 1
        if transition or first_free:
            self.found_free += 1
            self.store.log_event(
                self.checker.NAME, name, f"became available ({len(name)} letters)"
            )
            alert(self.checker.NAME, name, len(name))
        elif not self.quiet and verdict == UNKNOWN:
            print(f"{DIM}[{self.checker.NAME}] {name}: unknown ({note}){RESET}", flush=True)

    async def _worker(self) -> None:
        while not self._stopped.is_set():
            if time.monotonic() < self._cooldown_until:
                await asyncio.sleep(min(10.0, self._cooldown_until - time.monotonic()))
                continue
            batch = self.store.claim_free(self.checker.NAME, self.free_interval, limit=1)
            if not batch:
                batch = self.store.claim(self.checker.NAME, self.min_interval, limit=1)
            if not batch:
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(self._pace())
            if self._stopped.is_set():
                break
            await self._check_one(batch[0])

    def pending(self) -> int:
        return len(self.store.claim(self.checker.NAME, self.min_interval, limit=10**6))

    async def run(
        self,
        once: bool = False,
        limit: int | None = None,
        minutes: float | None = None,
    ) -> None:
        workers = [
            asyncio.create_task(self._worker()) for _ in range(self.checker.CONCURRENCY)
        ]
        started = time.monotonic()
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(1)
                if limit and self.checked >= limit:
                    break
                if minutes and time.monotonic() - started >= minutes * 60.0:
                    break
                if once and self.pending() == 0:
                    if self._idle_since is None:
                        self._idle_since = time.monotonic()
                    elif time.monotonic() - self._idle_since > 3:
                        break
        finally:
            try:
                self.store.log_event(
                    self.checker.NAME,
                    "",
                    f"run: checked {self.checked}, free {self.found_free}",
                )
            except Exception:
                pass
            self._stopped.set()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
