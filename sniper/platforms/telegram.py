import aiohttp

from .base import AVAILABLE, TAKEN, UNKNOWN, BaseChecker, RateLimited

URL = "https://t.me/{name}"


class TelegramChecker(BaseChecker):
    NAME = "telegram"
    DEFAULT_DELAY = 2.5
    CONCURRENCY = 1
    BACKOFF_START = 300.0

    async def check(self, name: str) -> tuple[str, str | None]:
        try:
            async with self.session.get(
                URL.format(name=name), timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 429:
                    raise RateLimited("telegram says slow down (http 429)")
                if r.status != 200:
                    return UNKNOWN, f"http {r.status}"
                body = await r.text()
        except (aiohttp.ClientError, TimeoutError) as e:
            return UNKNOWN, str(e)[:80]
        if "tgme_page_title" in body:
            return TAKEN, None
        return AVAILABLE, None
