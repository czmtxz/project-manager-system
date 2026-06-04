import sqlite3
db = sqlite3.connect('/opt/project_manager/project_manager/project_manager.db')
rows = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql LIKE '%transport_records%'").fetchall()
for r in rows:
    print(r[0])
    print('---')
