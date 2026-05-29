# -*- coding: utf-8 -*-
"""将指定项目下全部项目费用的分类改为指定末级科目。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3

TARGET_CATEGORY_NAME = "销售业务招待费"


def main():
    db = sqlite3.connect("project_manager.db")
    db.row_factory = sqlite3.Row

    proj = db.execute(
        "SELECT id, name FROM projects ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if len(sys.argv) > 1:
        row = db.execute(
            "SELECT id, name FROM projects WHERE name LIKE ? LIMIT 1",
            (f"%{sys.argv[1]}%",),
        ).fetchone()
        if row:
            proj = row

    cat = db.execute(
        "SELECT id, name FROM categories WHERE name=?", (TARGET_CATEGORY_NAME,)
    ).fetchone()
    if not proj or not cat:
        print("FAIL: project or category not found")
        return 1

    pid, cid = proj["id"], cat["id"]
    before = db.execute(
        """SELECT COUNT(*) FROM transaction_records
           WHERE project_id=? AND (category_id IS NULL OR category_id!=?)""",
        (pid, cid),
    ).fetchone()[0]

    db.execute(
        "UPDATE transaction_records SET category_id=? WHERE project_id=?",
        (cid, pid),
    )
    db.commit()

    total = db.execute(
        "SELECT COUNT(*) FROM transaction_records WHERE project_id=?", (pid,)
    ).fetchone()[0]
    print(f"OK project [{proj['name']}] id={pid}")
    print(f"   category: {cat['name']} (id={cid})")
    print(f"   updated {before} rows, total {total} expense records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
