"""为指定项目配置费用分类白名单（仅末级科目）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
from project_category_utils import (
    set_project_categories,
    get_project_enabled_category_ids,
    is_leaf_category,
)

# 本项目仅启用以下末级科目
TARGET_NAMES = ("销售差旅费", "销售业务招待费")


def main():
    db = sqlite3.connect("project_manager.db")
    db.row_factory = sqlite3.Row
    proj = db.execute(
        "SELECT id, name FROM projects ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if len(sys.argv) > 1:
        proj = db.execute(
            "SELECT id, name FROM projects WHERE name LIKE ? LIMIT 1",
            (f"%{sys.argv[1]}%",),
        ).fetchone() or proj

    if not proj:
        print("FAIL: 未找到项目")
        return 1

    pid = proj["id"]
    ids = []
    for name in TARGET_NAMES:
        row = db.execute(
            "SELECT id, name, level FROM categories WHERE name=?", (name,)
        ).fetchone()
        if not row:
            print(f"FAIL: 未找到科目「{name}」")
            return 1
        if not is_leaf_category(db, row["id"]):
            print(f"WARN: 「{name}」不是末级科目，仍将写入 id={row['id']}")
        ids.append(row["id"])
        print(f"  + {row['name']} (id={row['id']}, level={row['level']})")

    set_project_categories(db, pid, ids)
    db.commit()
    enabled = get_project_enabled_category_ids(db, pid)
    print(f"OK 项目 [{proj['name']}] id={pid} 已启用 {len(enabled)} 项: {enabled}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
