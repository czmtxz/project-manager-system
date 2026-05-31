#!/usr/bin/env python3
"""Quick verify truck_count column and sample data."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "project_manager.db"
cid = int(sys.argv[1]) if len(sys.argv) > 1 else 1

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
cols = [r[1] for r in db.execute("PRAGMA table_info(client_deductions)").fetchall()]
print("has truck_count:", "truck_count" in cols)
rows = db.execute(
    """SELECT item_name, truck_count, quantity, unit_price, amount
       FROM client_deductions WHERE customer_id=? ORDER BY id LIMIT 5""",
    (cid,),
).fetchall()
print("sample rows:")
for r in rows:
    print(dict(r))
total = db.execute(
    "SELECT COUNT(*), COALESCE(SUM(truck_count),0), COALESCE(SUM(amount),0) "
    "FROM client_deductions WHERE customer_id=?",
    (cid,),
).fetchone()
print(f"deductions: {total[0]} rows, trucks={total[1]}, amount={total[2]}")
pending = db.execute(
    "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM client_recharges "
    "WHERE customer_id=? AND status='pending'",
    (cid,),
).fetchone()
print(f"pending recharges: {pending[0]} rows, {pending[1]} yuan")
