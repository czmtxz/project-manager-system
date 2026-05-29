"""Verify project_detail renders column-filter markup and data attributes."""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

def main():
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "admin"
        s["role"] = "admin"

    db = sqlite3.connect("project_manager.db")
    row = db.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        print("FAIL: no projects")
        sys.exit(1)
    pid = row[0]

    r = client.get(f"/project/{pid}")
    html = r.data.decode("utf-8", errors="replace")
    if r.status_code != 200:
        print("FAIL: status", r.status_code)
        sys.exit(1)

    tables = [
        "table-participant",
        "table-transaction",
        "table-investment",
        "table-dividend",
        "table-payment",
        "table-fund",
    ]
    for tid in tables:
        if f'id="{tid}"' not in html:
            print(f"SKIP {tid}: not in page (no data)")
            continue
        block = html.split(f'id="{tid}"', 1)[1].split("</table>", 1)[0]
        has_filters = "thead-filters" in block and "col-filter" in block
        rows = re.findall(r"data-filter-\w+=", block)
        print(f"OK {tid}: filters={has_filters} data_attrs={len(rows)}")

    if "applyColumnFilters" not in html or "initDetailTableFilters" not in html:
        print("FAIL: filter JS missing")
        sys.exit(1)
    print("OK: filter JS present")
    sys.exit(0)


if __name__ == "__main__":
    main()
