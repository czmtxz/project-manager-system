import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db = sqlite3.connect("project_manager.db")
db.row_factory = sqlite3.Row
pid = 11
rows = db.execute(
    """
    SELECT c.id, c.name, c.type
    FROM project_categories pc
    JOIN categories c ON c.id = pc.category_id
    WHERE pc.project_id=?
    ORDER BY c.type, c.name
    """,
    (pid,),
).fetchall()
print("enabled_count", len(rows))
print("expense sample", [r["name"] for r in rows if r["type"] == "expense"][:15])
print("has_zhaodai", any("招待" in r["name"] for r in rows))
print("has_chailv", any("差旅" in r["name"] for r in rows))
