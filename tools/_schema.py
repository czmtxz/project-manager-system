# -*- coding: utf-8 -*-
import sqlite3, os
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB)
t = os.environ.get('T', 'sales_order_items')
print(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0])
print('--- columns ---')
for r in db.execute("PRAGMA table_info(%s)" % t).fetchall():
    print(r)
db.close()
