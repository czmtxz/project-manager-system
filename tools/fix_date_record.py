#!/usr/bin/env python3
"""Find and update records with date 2025-05-18 -> 2026-06-18."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "project_manager.db"
OLD = "2025-05-18"
NEW = "2026-06-18"
DRY = "--apply" not in sys.argv

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

DATE_TABLES = [
    ("client_deductions", "deduct_date"),
    ("client_recharges", "created_at"),
]

found = []
for table, col in DATE_TABLES:
    rows = db.execute(
        f"SELECT * FROM {table} WHERE {col} LIKE ? OR {col} LIKE ?",
        (f"{OLD}%", f"{OLD.replace('-', '.')}%"),
    ).fetchall()
    for r in rows:
        found.append((table, col, dict(r)))

if not found:
    # broader search
    for table, col in DATE_TABLES:
        rows = db.execute(
            f"SELECT * FROM {table} WHERE {col} LIKE '%2025%05%18%' OR {col} LIKE '%2025.05.18%'"
        ).fetchall()
        for r in rows:
            found.append((table, col, dict(r)))

print(f"Found {len(found)} record(s) matching {OLD}")
for table, col, row in found:
    print(f"  [{table}] id={row.get('id')} {col}={row.get(col)!r} item={row.get('item_name','')} amount={row.get('amount','')}")

if not found:
    sys.exit(0)

if DRY:
    print("\nDry run. Pass --apply to update.")
    sys.exit(0)

for table, col, row in found:
    old_val = row[col]
    if old_val.startswith(OLD):
        new_val = NEW + old_val[len(OLD):]
    else:
        new_val = NEW
    db.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (new_val, row["id"]))
    print(f"Updated {table} id={row['id']}: {old_val!r} -> {new_val!r}")

db.commit()
print("Done.")
