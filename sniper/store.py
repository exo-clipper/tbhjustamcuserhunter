import sqlite3
import time
from pathlib import Path

# available: -1 unknown | 0 taken | 1 claimable now | 2 ownerless but locked
# flip_ts:   epoch when we watched the owner vanish (0 = history unknown)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    platform     TEXT NOT NULL,
    name         TEXT NOT NULL,
    available    INTEGER NOT NULL DEFAULT -1,
    last_checked REAL NOT NULL DEFAULT 0,
    changed_at   REAL NOT NULL DEFAULT 0,
    checks       INTEGER NOT NULL DEFAULT 0,
    flip_ts      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, name)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_due ON names (platform, last_checked);
CREATE INDEX IF NOT EXISTS idx_state ON names (platform, available);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    platform TEXT NOT NULL,
    name     TEXT NOT NULL,
    detail   TEXT NOT NULL
);
"""

_MIGRATIONS = (
    ("flip_ts", "ALTER TABLE names ADD COLUMN flip_ts REAL NOT NULL DEFAULT 0"),
)


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(names)").fetchall()
        }
        for col, ddl in _MIGRATIONS:
            if col not in cols:
                self.conn.execute(ddl)
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

    def claim(
        self, platform: str, min_interval: float, limit: int = 1
    ) -> list[str]:
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND last_checked <= ? ORDER BY last_checked LIMIT ?",
            (platform, now - min_interval, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def claim_hot(
        self, platform: str, names: list[str], min_interval: float, limit: int = 5
    ) -> list[str]:
        if not names:
            return []
        now = time.time()
        out: list[str] = []
        for i in range(0, len(names), 50):
            chunk = names[i : i + 50]
            ph = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT name FROM names WHERE platform = ? AND name IN ({ph}) "
                "AND last_checked <= ? ORDER BY last_checked LIMIT ?",
                (platform, *chunk, now - min_interval, limit - len(out)),
            ).fetchall()
            out.extend(r[0] for r in rows)
            if len(out) >= limit:
                break
        return out[:limit]

    def claim_free(
        self, platform: str, max_age: float, limit: int = 1
    ) -> list[str]:
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND available = 1 AND last_checked <= ? "
            "ORDER BY last_checked LIMIT ?",
            (platform, now - max_age, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def claim_strikes(
        self, platform: str, cooldown: float, lead: float, limit: int = 10
    ) -> list[str]:
        """Names whose owner vanished and whose lock expires within `lead` s."""
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND available = 2 AND flip_ts > 0 "
            "AND flip_ts + ? <= ? ORDER BY flip_ts LIMIT ?",
            (platform, cooldown, now + lead, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def claim_probes(
        self, platform: str, every: float, limit: int = 3
    ) -> list[str]:
        """Ownerless names with unknown history that need a ?at= probe."""
        now = time.time()
        rows = self.conn.execute(
            "SELECT name FROM names "
            "WHERE platform = ? AND available = 2 AND flip_ts = 0 "
            "AND last_checked <= ? ORDER BY last_checked LIMIT ?",
            (platform, now - every, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def record_result(
        self,
        platform: str,
        name: str,
        taken: bool,
        cooldown: float | None = None,
        now: float | None = None,
    ) -> str | None:
        """Apply a taken/ownerless verdict; returns an event line or None."""
        if cooldown is None:
            from . import settings

            cooldown = settings.COOLDOWN
        now = time.time() if now is None else now
        row = self.conn.execute(
            "SELECT available, flip_ts, changed_at FROM names "
            "WHERE platform = ? AND name = ?",
            (platform, name),
        ).fetchone()
        old = row[0] if row else -1
        ev: str | None = None
        if taken:
            new, flip = 0, 0.0
            if old in (1, 2):
                ev = "gone - claimed by someone"
        else:
            if old == 0:
                new, flip = 2, now
                when = time.strftime("%m-%d %H:%M", time.localtime(now + cooldown))
                ev = f"dropped by owner - claimable ~{when}"
            elif old == 2:
                flip = row[1] if row else 0.0
                if flip > 0 and now >= flip + cooldown:
                    new = 1
                    ev = "claimable NOW"
                else:
                    new = 2
            elif old == -1:
                # first sight of an ownerless name: history unknown, so
                # hide it until a ?at= probe proves no recent owner
                new, flip = 2, 0.0
            else:
                new, flip = 1, 0.0
        changed_at = now
        if row and old != -1 and new == old:
            changed_at = row[2]
        self.conn.execute(
            "INSERT INTO names (platform, name, available, last_checked, "
            "changed_at, checks, flip_ts) VALUES (?, ?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(platform, name) DO UPDATE SET available = ?, "
            "last_checked = ?, changed_at = ?, checks = checks + 1, flip_ts = ?",
            (
                platform, name, new, now, changed_at, flip,
                new, now, changed_at, flip,
            ),
        )
        self.conn.commit()
        return ev

    def record_probe(
        self, platform: str, name: str, had_owner: bool | None,
        now: float | None = None,
    ) -> str | None:
        """Fold a ?at= history probe into an unknown-history (state 2) name."""
        now = time.time() if now is None else now
        row = self.conn.execute(
            "SELECT available, changed_at FROM names "
            "WHERE platform = ? AND name = ?",
            (platform, name),
        ).fetchone()
        if not row or row[0] != 2:
            return None
        old, changed_at = row
        ev: str | None = None
        new = 2
        flip = 0.0
        if had_owner is False:
            new = 1
            changed_at = now
            ev = "claimable (verified via history)"
        self.conn.execute(
            "UPDATE names SET available = ?, last_checked = ?, "
            "changed_at = ?, checks = checks + 1, flip_ts = ? "
            "WHERE platform = ? AND name = ?",
            (new, now, changed_at, flip, platform, name),
        )
        self.conn.commit()
        return ev

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
