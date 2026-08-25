AVAILABLE = "available"
TAKEN = "taken"
UNKNOWN = "unknown"


class RateLimited(Exception):
    """Raised when the platform tells us to slow down."""


class CheckerDisabled(Exception):
    """Raised when a checker cannot run (e.g. missing token)."""


class BaseChecker:
    NAME: str = ""
    DEFAULT_DELAY: float = 1.0
    CONCURRENCY: int = 4
    BACKOFF_START: float = 30.0

    def __init__(self, session, **opts):
        self.session = session
        self.backoff_until = 0.0

    async def check(self, name: str) -> tuple[str, str | None]:
        raise NotImplementedError

    async def close(self) -> None:
        return None
