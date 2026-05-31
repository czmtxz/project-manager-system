# -*- coding: utf-8 -*-
import sqlite3, os
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
rows = db.execute("SELECT id, client_id, amount, status, created_at, remark FROM client_recharges ORDER BY id").fetchall()
print('total recharges:', len(rows))
for r in rows[:30]:
    print(r['id'], r['client_id'], r['amount'], r['status'], (r['remark'] or '')[:30])
db.close()
