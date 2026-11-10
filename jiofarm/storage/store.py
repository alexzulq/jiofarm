"""JioFarm — SQLite storage layer."""

from __future__ import annotations

import sqlite3
import threading


class Store:
    """Thread-safe SQLite store for hunt results."""

    def __init__(self, path: str = "results.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS hunts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    activation_id TEXT,
                    otp TEXT,
                    logged_in INTEGER DEFAULT 0,
                    link TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )""")

    def save(
        self,
        phone: str,
        act_id: str | None,
        otp: str | None,
        logged_in: bool,
        link: str | None,
    ) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO hunts (phone, activation_id, otp, logged_in, link) "
                "VALUES (?,?,?,?,?)",
                (phone, act_id, otp, int(logged_in), link),
            )

    def all_links(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT link FROM hunts WHERE link IS NOT NULL AND link != '' "
            "ORDER BY id DESC"
        )
        return [r["link"] for r in cur.fetchall()]

    def all_links_detailed(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, phone, activation_id, otp, logged_in, link, created_at "
            "FROM hunts WHERE link IS NOT NULL AND link != '' "
            "ORDER BY id DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def recent_hunts(self, limit: int = 50) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, phone, activation_id, otp, logged_in, link, created_at "
            "FROM hunts ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def stats(self) -> dict:
        cur = self.conn.execute(
            "SELECT COUNT(*) n, SUM(logged_in) logins, "
            "SUM(CASE WHEN link IS NOT NULL AND link != '' THEN 1 ELSE 0 END) links "
            "FROM hunts"
        )
        row = cur.fetchone()
        return {
            "hunts": row["n"] or 0,
            "logins": row["logins"] or 0,
            "links": row["links"] or 0,
        }