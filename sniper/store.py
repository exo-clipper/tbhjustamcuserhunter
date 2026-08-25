import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    platform     TEXT NOT NULL,
    name         TEXT NOT NULL,
    available    INTEGER NOT NULL DEFAULT -1,
    last_checked REAL NOT NULL DEFAULT 0,
    changed_at   REAL NOT NULL DEFAULT 0,
    checks       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, name)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_due ON names (platform, last_checked);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    platform TEXT NOT NULL,
    name     TEXT NOT NULL,
    detail   TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def add_names(self, platform: str, names: list[str]) -> int:
        cur = self.conn.executemany(
            "INSERT OR IGNORE INTO names (platform, name) VALUES (?, ?)",
            [(platform, n) for n in names],
        )
        self.conn.commit()
        return cur.rowcount

    def remove_names(self, platform: str, names: list[str]) -> int:
        cur = self.conn.executemany(
            "DELETE FROM names WHERE platform = ? AND name = ?",
            [(platform, n) for n in names],
        )
        self.conn.commit()
        return cur.rowcount

    def prune_missing(self, platform: str, keep: set[str]) -> int:
        rows = self.conn.execute(
            "SELECT name FROM names WHERE platform = ?", (platform,)
        ).fetchall()
        drop = [(r[0],) for r in rows if r[0] not in keep]
        if drop:
            self.conn.executemany(
                "DELETE FROM names WHERE platform = ? AND name = ?",
                [(platform, n) for (n,) in drop],
            )
            self.conn.commit()
        return len(drop)

    def claim(self, platform: str, min_interval: float, limit: int = 1) -> list[str]:
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND last_checked <= ? ORDER BY last_checked LIMIT ?",
            (platform, now - min_interval, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def claim_free(self, platform: str, max_age: float, limit: int = 1) -> list[str]:
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND available = 1 AND last_checked <= ? "
            "ORDER BY last_checked LIMIT ?",
            (platform, now - max_age, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def record(
        self, platform: str, name: str, available: bool | None
    ) -> tuple[bool, bool]:
        """Returns (transition_to_free, first_time_available)."""
        now = time.time()
        row = self.conn.execute(
            "SELECT available, changed_at FROM names WHERE platform = ? AND name = ?",
            (platform, name),
        ).fetchone()
        old = row[0] if row else -1
        new = -1 if available is None else (1 if available else 0)
        changed_at = now if (old == -1 or new != old) else (row[1] if row else now)
        self.conn.execute(
            "UPDATE names SET available = ?, last_checked = ?, changed_at = ?, "
            "checks = checks + 1 WHERE platform = ? AND name = ?",
            (new, now, changed_at, platform, name),
        )
        self.conn.commit()
        transition = old == 0 and new == 1
        first_free = new == 1 and old != 1 and not transition
        return transition, first_free

    def log_event(self, platform: str, name: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, platform, name, detail) VALUES (?, ?, ?, ?)",
            (time.time(), platform, name, detail),
        )
        self.conn.commit()

    def stats(self) -> dict:
        out: dict = {}
        for plat, avail, cnt in self.conn.execute(
            "SELECT platform, available, COUNT(*) FROM names GROUP BY platform, available"
        ):
            out.setdefault(plat, {})[int(avail)] = cnt
        return out

    def free_names(self, platform: str) -> list[tuple[str, float]]:
        return [
            (r[0], r[1])
            for r in self.conn.execute(
                "SELECT name, changed_at FROM names "
                "WHERE platform = ? AND available = 1 ORDER BY changed_at DESC",
                (platform,),
            )
        ]
