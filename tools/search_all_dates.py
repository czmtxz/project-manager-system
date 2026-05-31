#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "project_manager.db"
db = sqlite3.connect(DB)

needles = ["2025-05-18", "2025.05.18", "2025/05/18"]
tables = [r[0] for r in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]

for t in tables:
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({t})").fetchall()]
    for c in cols:
        for n in needles:
            try:
                rows = db.execute(
                    f"SELECT id, {c} FROM {t} WHERE CAST({c} AS TEXT) LIKE ?",
                    (f"%{n}%",),
                ).fetchall()
                for row in rows:
                    print(f"{t}.{c} id={row[0]}: {row[1]!r}")
            except sqlite3.OperationalError:
                pass
