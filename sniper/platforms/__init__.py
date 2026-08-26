from .base import AVAILABLE, TAKEN, UNKNOWN, BaseChecker, RateLimited
from .minecraft import MinecraftChecker

CHECKERS = {
    "minecraft": MinecraftChecker,
}

__all__ = [
    "AVAILABLE",
    "TAKEN",
    "UNKNOWN",
    "BaseChecker",
    "RateLimited",
    "MinecraftChecker",
    "CHECKERS",
]
