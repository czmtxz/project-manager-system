#!/usr/bin/env python3
import sqlite3
import sys
sys.path.insert(0, '/opt/project_manager/project_manager')
from app import app

db = sqlite3.connect('/opt/project_manager/project_manager/project_manager.db')
cur = db.execute(
    "INSERT INTO transport_records (sales_order_id, batch_no, quantity, freight_amount) VALUES (14, 'test-del', 1, 1)"
)
db.commit()
tid = cur.lastrowid
print('created', tid)

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    r = c.post(f'/api/transport/{tid}/delete')
    print('delete', r.status_code, r.get_data(as_text=True))

row = db.execute('SELECT id FROM transport_records WHERE id=?', (tid,)).fetchone()
print('still exists', bool(row))
