#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "project_manager.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

patterns = ["2025-05-18", "2025.05.18", "2025/05/18", "2026-05-18", "2025-06-18", "2026.05.18"]
for p in patterns:
    rows = db.execute(
        "SELECT cd.id, cd.deduct_date, cd.item_name, cd.amount, ca.company_name "
        "FROM client_deductions cd JOIN client_accounts ca ON cd.client_id=ca.id "
        "WHERE cd.deduct_date LIKE ? OR cd.remark LIKE ?",
        (f"%{p}%", f"%{p}%"),
    ).fetchall()
    if rows:
        print(f"deductions {p}:", len(rows))
        for r in rows:
            print(" ", dict(r))

    rows = db.execute(
        "SELECT cr.id, cr.created_at, cr.amount, cr.remark, ca.company_name "
        "FROM client_recharges cr JOIN client_accounts ca ON cr.client_id=ca.id "
        "WHERE cr.created_at LIKE ? OR cr.remark LIKE ?",
        (f"%{p}%", f"%{p}%"),
    ).fetchall()
    if rows:
        print(f"recharges {p}:", len(rows))
        for r in rows:
            print(" ", dict(r))

# show deductions around May 2025/2026
print("\n--- deductions in May ---")
rows = db.execute(
    "SELECT cd.id, cd.deduct_date, cd.item_name, cd.amount "
    "FROM client_deductions cd WHERE deduct_date LIKE '%-05-18%' OR deduct_date LIKE '%.05.18%'"
).fetchall()
for r in rows:
    print(dict(r))
