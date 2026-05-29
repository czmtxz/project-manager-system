import sqlite3

db = sqlite3.connect("project_manager.db")
db.row_factory = sqlite3.Row
for kw in ("招待费", "差旅费"):
    rows = db.execute(
        "SELECT id, code, level, name, type FROM categories WHERE name LIKE ? ORDER BY id",
        (f"%{kw}%",),
    ).fetchall()
    print("==", kw, "==")
    for r in rows:
        print(dict(r))
