import asyncio
import os

import aiohttp


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


async def _post(session: aiohttp.ClientSession, url: str, **kw) -> None:
    try:
        async with session.post(
            url, timeout=aiohttp.ClientTimeout(total=10), **kw
        ):
            pass
    except Exception:
        pass


async def push(platform: str, name: str, length: int) -> None:
    topic = _env("ALERT_NTFY")
    token = _env("ALERT_TG_TOKEN")
    chat = _env("ALERT_TG_CHAT")
    if not topic and not (token and chat):
        return
    text = (
        f"new {length} letter username available\n"
        f"@{name}  ->  https://t.me/{name}"
    )
    async with aiohttp.ClientSession() as s:
        if topic:
            await _post(
                s,
                f"https://ntfy.sh/{topic}",
                data=text.encode(),
                headers={
                    "Title": f"@{name} is free",
                    "Tags": "rotating_light",
                    "Priority": "high",
                },
            )
        if token and chat:
            await _post(
                s,
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text},
            )


def fire_and_forget(platform: str, name: str, length: int) -> None:
    try:
        asyncio.get_running_loop().create_task(push(platform, name, length))
    except RuntimeError:
        pass
