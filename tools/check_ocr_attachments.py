# -*- coding: utf-8 -*-
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "uploads"
DB = ROOT / "project_manager.db"

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
rows = c.execute(
    "SELECT id, attachment, source FROM transaction_records "
    "WHERE attachment IS NOT NULL AND attachment != '' "
    "ORDER BY id DESC LIMIT 20"
).fetchall()
for r in rows:
    att = r["attachment"]
    p1 = UP / att
    p2 = UP / "ocr" / os.path.basename(att)
    ok = p1.is_file() or p2.is_file()
    print(r["id"], r["source"], att, "OK" if ok else "MISSING")
