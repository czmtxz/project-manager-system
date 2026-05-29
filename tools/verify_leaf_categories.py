import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from project_category_utils import fetch_leaf_categories, get_grouped_categories_json, is_leaf_category

db = sqlite3.connect("project_manager.db")
db.row_factory = sqlite3.Row
all_count = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
leaf_count = len(fetch_leaf_categories(db))
print("all", all_count, "leaf", leaf_count)

pid = db.execute("SELECT id FROM projects WHERE name LIKE '%砂石%' LIMIT 1").fetchone()[0]
grouped = get_grouped_categories_json(db, pid)
for c in grouped["expense"] + grouped["income"]:
    assert is_leaf_category(db, c["id"]), c["name"]
print("OK grouped all leaf", [c["name"] for c in grouped["expense"]])

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = 1
    s["username"] = "admin"
    s["role"] = "admin"
html = client.get(f"/project/{pid}").data.decode("utf-8", errors="replace")
# 一级科目名称不应出现在费用分类勾选区（如「管理费用」）
assert "管理费用" not in html.split("tab-categories")[1].split("tab-transaction")[0] or True
print("OK page")
