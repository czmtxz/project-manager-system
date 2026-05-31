#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "project_manager.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

OLD = "2025-05-18"
NEW_DATE = "2026-06-18"
NEW_REMARK = "2026-06-18"

# Update recharge id=83: remark and created_at date part
r = db.execute("SELECT * FROM client_recharges WHERE id=83").fetchone()
if r:
    print("Before:", dict(r))
    new_remark = (r["remark"] or "").replace("2025-05-18", NEW_REMARK).replace("2025.05.18", "2026.06.18")
    # keep time part if any, set business date on created_at
    old_created = r["created_at"] or ""
    time_part = old_created[10:] if len(old_created) > 10 else " 00:00:00"
    new_created = NEW_DATE + time_part
    db.execute(
        "UPDATE client_recharges SET remark=?, created_at=? WHERE id=?",
        (new_remark, new_created, 83),
    )
    db.commit()
    r2 = db.execute("SELECT * FROM client_recharges WHERE id=83").fetchone()
    print("After:", dict(r2))
else:
    print("Record 83 not found")
