# -*- coding: utf-8 -*-
import sqlite3
import json

db = sqlite3.connect('project_manager.db')
db.row_factory = sqlite3.Row
print('max_id:', db.execute('SELECT MAX(id) FROM transaction_records').fetchone()[0])
print('count:', db.execute('SELECT COUNT(*) FROM transaction_records').fetchone()[0])
for rid in (96, 97):
    r = db.execute('SELECT id, project_id, trans_date, amount, trans_type, category_id, participant_id, description FROM transaction_records WHERE id=?', (rid,)).fetchone()
    print('id %d ->' % rid, json.dumps(dict(r), ensure_ascii=False) if r else 'MISSING')
print('--- recent >= 2026-05-25 ---')
for r in db.execute("SELECT id, project_id, trans_date, amount, trans_type FROM transaction_records WHERE trans_date>='2026-05-25' ORDER BY trans_date DESC").fetchall():
    print(json.dumps(dict(r), ensure_ascii=False))
