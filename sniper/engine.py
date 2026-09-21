import asyncio
import random
import time
from pathlib import Path

from . import settings
from .platforms.base import AVAILABLE, TAKEN, UNKNOWN, CheckerDisabled, RateLimited

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"

DATA_DIR = Path(__file__).parent / "data"
ALERT_LOG = DATA_DIR / "alerts.log"


def alert(platform: str, name: str) -> None:
    line = f"*** {platform.upper()} {name} IS CLAIMABLE -> minecraft.net profile"
    print(f"\n{GREEN}{line}{RESET}\a", flush=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    with open(DATA_DIR / f"free_{platform}.txt", "a", encoding="utf-8") as f:
        f.write(f"{name}\n")


class PlatformRunner:
    """Batch-paced watcher: drop strikes > history probes > free re-checks >
    hot lane > full sweep."""

    def __init__(self, store, checker, delay=None, quiet=False):
        self.store = store
        self.checker = checker
        platform = checker.NAME
        self.platform = platform
        self.delay = delay if delay is not None else checker.DEFAULT_DELAY
        self.quiet = quiet
        self.hot: list[str] = []
        self.checked = 0
        self.found_free = 0
        self._last_dispatch = 0.0
        self._stopped = asyncio.Event()
        self._idle_since: float | None = None
        self._strikes = 0
        self._level = 0
        self._cooldown_until = 0.0

    def set_hot(self, names: list[str]) -> None:
        self.hot = list(names)

    def stopping(self) -> bool:
        return self._stopped.is_set()

    def _pace(self) -> float:
        now = time.monotonic()
        step = max(0.5, self.delay * (1.0 + random.uniform(-settings.JITTER, settings.JITTER)))
        wait = self._last_dispatch + step - now
        self._last_dispatch = max(now, self._last_dispatch + step)
        return max(wait, 0.0)

    def _trip_breaker(self, reason: str) -> None:
        cooldown = min(settings.BREAKER_MAX, settings.BREAKER_START * (2**self._level))
        self._level += 1
        self._strikes = 0
        self._cooldown_until = time.monotonic() + cooldown
        mins = int(cooldown // 60)
        self.store.log_event(
            self.platform, "", f"breaker: paused {mins}m ({reason})"
        )
        print(
            f"{RED}[{self.platform}] possible rate limiting ({reason}) "
            f"-> pausing this shard for {mins} min{RESET}",
            flush=True,
        )

    def _compose(self) -> tuple[list[str], list[str]]:
        cap = settings.BATCH_SIZE
        batch: list[str] = []
        seen: set[str] = set()
        probes = self.store.claim_probes(self.platform, settings.PROBE_EVERY, 2)

        # 1) free re-checks first, always. These are the names the user is
        #    about to click; when a cluster of 37-day unlocks saturates the
        #    strike lane, frees must not starve behind it.
        if cap:
            frees = self.store.claim_free(
                self.platform, settings.FREE_RECHECK, min(4, cap)
            )
            for n in frees:
                if n not in seen:
                    batch.append(n)
                    seen.add(n)

        # 2) drop strikes: fast-poll toward each unlock second. One batch of
        #    delay is harmless (the poll repeats every cycle).
        if len(batch) < cap:
            strikes = self.store.claim_strikes(
                self.platform, settings.COOLDOWN, settings.STRIKE_LEAD,
                cap - len(batch),
            )
            for n in strikes:
                if n not in seen:
                    batch.append(n)
                    seen.add(n)

        # 3) hot lane
        if len(batch) < cap:
            hot = self.store.claim_hot(
                self.platform, self.hot, settings.HOT_RECHECK,
                min(5, cap - len(batch)),
            )
            for n in hot:
                if n not in seen:
                    batch.append(n)
                    seen.add(n)

        # 4) full sweep
        if len(batch) < cap:
            regular = self.store.claim(
                self.platform, settings.SWEEP_INTERVAL, cap - len(batch)
            )
            for n in regular:
                if n not in seen:
                    batch.append(n)
                    seen.add(n)

        # 5) spare capacity: more free re-checks
        if len(batch) < cap:
            frees = self.store.claim_free(
                self.platform, settings.FREE_RECHECK, cap - len(batch)
            )
            for n in frees:
                if n not in seen:
                    batch.append(n)
                    seen.add(n)

        return batch[:cap], probes

    async def _handle_batch(self, names: list[str]) -> None:
        results = await self.checker.check_batch(names)
        for name in names:
            verdict, note = results.get(name, (UNKNOWN, "no result"))
            if verdict == UNKNOWN:
                if not self.quiet:
                    print(f"{DIM}[{self.platform}] {name}: unknown ({note}){RESET}", flush=True)
                continue
            self.checked += 1
            ev = self.store.record_result(self.platform, name, verdict == TAKEN)
            if not ev:
                continue
            self.store.log_event(self.platform, name, ev)
            if ev.startswith("claimable"):
                self.found_free += 1
                alert(self.platform, name)
            elif ev.startswith("dropped"):
                print(f"{GREEN}[{self.platform}] {name}: {ev}{RESET}", flush=True)
            else:
                print(f"{YELLOW}[{self.platform}] {name}: {ev}{RESET}", flush=True)

    async def _run_probes(self, names: list[str]) -> None:
        for name in names:
            await asyncio.sleep(self._pace())
            had_owner = await self.checker.probe_history(name)
            if had_owner is True and not self.quiet:
                print(f"{DIM}[{self.platform}] {name}: owned recently, staying hidden{RESET}", flush=True)
            ev = self.store.record_probe(self.platform, name, had_owner)
            if ev:
                self.store.log_event(self.platform, name, ev)
                self.found_free += 1
                alert(self.platform, name)

    async def _worker(self) -> None:
        while not self._stopped.is_set():
            if time.monotonic() < self._cooldown_until:
                await asyncio.sleep(min(10.0, self._cooldown_until - time.monotonic()))
                continue
            batch, probes = self._compose()
            if not batch and not probes:
                await asyncio.sleep(2)
                continue
            try:
                if batch:
                    await asyncio.sleep(self._pace())
                    if self._stopped.is_set():
                        break
                    await self._handle_batch(batch)
                await self._run_probes(probes)
            except RateLimited as e:
                self._strikes += 1
                self.store.log_event(self.platform, "", f"throttle: {e}")
                print(f"{YELLOW}[{self.platform}] {e}{RESET}", flush=True)
                if self._strikes >= settings.BREAKER_THRESHOLD:
                    self._trip_breaker(str(e)[:60])

    async def run(
        self,
        once: bool = False,
        limit: int | None = None,
        minutes: float | None = None,
    ) -> None:
        workers = [
            asyncio.create_task(self._worker())
            for _ in range(max(1, self.checker.CONCURRENCY))
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
                    self.platform,
                    "",
                    f"run: checked {self.checked}, claimable {self.found_free}",
                )
            except Exception:
                pass
            self._stopped.set()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    def pending(self) -> int:
        return len(self.store.claim(self.platform, settings.SWEEP_INTERVAL, limit=10**6))
