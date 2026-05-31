# -*- coding: utf-8 -*-
import sqlite3, os
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB)
print(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sales_orders'").fetchone()[0])
print('--- columns ---')
for r in db.execute("PRAGMA table_info(sales_orders)").fetchall():
    print(r)
db.close()
