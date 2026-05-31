#!/usr/bin/env python3
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from client_portal_utils import ensure_schema_extensions

db = sqlite3.connect(ROOT / "project_manager.db")
ensure_schema_extensions(db)
cols = [c[1] for c in db.execute("PRAGMA table_info(client_deductions)")]
print("has deduct_type:", "deduct_type" in cols)
for row in db.execute(
    "SELECT deduct_type, COUNT(*), COALESCE(SUM(amount),0) FROM client_deductions GROUP BY deduct_type"
):
    print(row)
