import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from sniper.platforms import telegram
from sniper.platforms.base import AVAILABLE, TAKEN, RateLimited


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path
        code, body = 500, b""
        if p == "/tg/taken":
            code, body = 200, b"<div class='tgme_page_title'>x</div>"
        elif p == "/tg/free":
            code, body = 200, b"<html><body>contact page</body></html>"
        elif p == "/tg/busy":
            code = 429
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1], srv.shutdown


async def main() -> int:
    port, stop = start_server()
    base = f"http://127.0.0.1:{port}"
    telegram.URL = base + "/tg/{name}"

    failures = 0

    async def expect(label, fn, want):
        nonlocal failures
        try:
            got = await fn()
            got = got[0] if isinstance(got, tuple) else got
        except RateLimited as e:
            got = f"RateLimited({e})"
        ok = got == want or (isinstance(want, str) and str(got).startswith(want))
        print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}")
        if not ok:
            failures += 1

    async with aiohttp.ClientSession() as s:
        tg = telegram.TelegramChecker(s)
        await expect("tg taken", lambda: tg.check("taken"), TAKEN)
        await expect("tg free", lambda: tg.check("free"), AVAILABLE)
        await expect("tg 429 raises", lambda: tg.check("busy"), "RateLimited")
    stop()
    print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
