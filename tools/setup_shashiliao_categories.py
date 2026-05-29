"""砂石料项目：仅启用业务招待费、管理人员差旅费"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
from project_category_utils import set_project_categories, get_project_enabled_category_ids

TARGET_NAMES = ("销售差旅费", "销售业务招待费")


def main():
    db = sqlite3.connect("project_manager.db")
    db.row_factory = sqlite3.Row
    proj = db.execute(
        "SELECT id, name FROM projects WHERE name LIKE ? ORDER BY id DESC LIMIT 1",
        ("%砂石%",),
    ).fetchone()
    if not proj:
        print("FAIL: 未找到砂石料项目")
        return 1
    pid = proj["id"]
    ids = []
    for name in TARGET_NAMES:
        row = db.execute("SELECT id, name FROM categories WHERE name=?", (name,)).fetchone()
        if row:
            ids.append(row["id"])
            print("  +", name, "id=", row["id"])
        else:
            print("  ! 未找到分类:", name)
    if len(ids) != len(TARGET_NAMES):
        print("FAIL: 分类不全")
        return 1
    set_project_categories(db, pid, ids)
    db.commit()
    enabled = get_project_enabled_category_ids(db, pid)
    print("OK project", pid, proj["name"], "enabled", len(enabled), enabled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
