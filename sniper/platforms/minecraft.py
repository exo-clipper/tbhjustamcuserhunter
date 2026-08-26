import time

import aiohttp

from .. import settings
from .base import AVAILABLE, TAKEN, UNKNOWN, BaseChecker, RateLimited

BULK_HOSTS = (
    "https://api.mojang.com/profiles/minecraft",
    "https://api.minecraftservices.com/minecraft/profile/lookup/bulk/byname",
)
SINGLE_URL = "https://api.mojang.com/users/profiles/minecraft/{name}"
HISTORY_URL = "https://api.mojang.com/users/profiles/minecraft/{name}?at={ts}"

_TIMEOUT = aiohttp.ClientTimeout(total=15)


class MinecraftChecker(BaseChecker):
    """Mojang profile lookups.

    The bulk endpoints accept up to BATCH_SIZE names and answer with only
    the profiles that currently exist. An absent name has no owner right
    now - either never claimed or locked in the 37-day post-change
    cooldown; the store sorts that out from observation history.
    """

    NAME = "minecraft"
    DEFAULT_DELAY = settings.BATCH_DELAY
    CONCURRENCY = 1

    def __init__(self, session, **opts):
        super().__init__(session, **opts)
        self._host = 0
        self._bad_streak = 0

    def _note_bad(self) -> None:
        self._bad_streak += 1
        if self._bad_streak >= settings.UNKNOWN_STRIKE_LIMIT:
            raise RateLimited(f"{self._bad_streak} bad responses in a row")

    async def _post_bulk(self, names: list[str]) -> dict[str, bool] | None:
        url = BULK_HOSTS[self._host % len(BULK_HOSTS)]
        self._host += 1
        try:
            async with self.session.post(url, json=names, timeout=_TIMEOUT) as r:
                if r.status == 429:
                    raise RateLimited("mojang says slow down (http 429)")
                if r.status != 200:
                    self._note_bad()
                    return None
                data = await r.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError):
            self._note_bad()
            return None
        self._bad_streak = 0
        found: dict[str, bool] = {}
        for row in data if isinstance(data, list) else []:
            n = str(row.get("name", "")).lower()
            if n:
                found[n] = True
        return found

    async def check_batch(
        self, names: list[str]
    ) -> dict[str, tuple[str, str | None]]:
        found = await self._post_bulk(list(names))
        if found is None:
            return {n: (UNKNOWN, "bad response") for n in names}
        return {
            n: ((TAKEN, None) if n in found else (AVAILABLE, None)) for n in names
        }

    async def check(self, name: str) -> tuple[str, str | None]:
        try:
            async with self.session.get(
                SINGLE_URL.format(name=name), timeout=_TIMEOUT
            ) as r:
                if r.status == 429:
                    raise RateLimited("mojang says slow down (http 429)")
                if r.status == 200:
                    self._bad_streak = 0
                    return TAKEN, None
                if r.status == 404:
                    self._bad_streak = 0
                    return AVAILABLE, None
                self._note_bad()
                return UNKNOWN, f"http {r.status}"
        except (aiohttp.ClientError, TimeoutError) as e:
            return UNKNOWN, str(e)[:80]

    async def probe_history(self, name: str) -> bool | None:
        """Did anyone own this name ~45 days ago?

        False means no owner existed then and it has none now, so any
        cooldown long expired - claimable for sure. True means an owner
        existed recently; stay hidden until direct observation proves the
        drop. None = inconclusive.
        """
        ts = int(time.time() - 45 * 86400)
        try:
            async with self.session.get(
                HISTORY_URL.format(name=name, ts=ts), timeout=_TIMEOUT
            ) as r:
                if r.status == 200:
                    return True
                if r.status == 404:
                    return False
                return None
        except (aiohttp.ClientError, TimeoutError):
            return None
