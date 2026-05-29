import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db = sqlite3.connect("project_manager.db")
db.row_factory = sqlite3.Row

print("category tables:", [r[0] for r in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%categor%'"
)])
print("projects:", [dict(r) for r in db.execute("SELECT id, name FROM projects")])
print("category cols:", [r[1] for r in db.execute("PRAGMA table_info(categories)")])
try:
    print("project_categories count:", db.execute("SELECT COUNT(*) FROM project_categories").fetchone()[0])
except Exception as e:
    print("project_categories:", e)
for kw in ("招待", "差旅"):
    rows = db.execute("SELECT id, name, type FROM categories WHERE name LIKE ?", (f"%{kw}%",)).fetchall()
    print(kw, [dict(r) for r in rows])
