# -*- coding: utf-8 -*-
"""将导出的项目费用记录应用到服务器数据库（按 id 做 INSERT OR REPLACE）。"""
import os
import json
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '_tr_export.json')

db = sqlite3.connect(os.path.join(os.path.dirname(HERE), 'project_manager.db'))
db.row_factory = sqlite3.Row

existing_cols = [r[1] for r in db.execute('PRAGMA table_info(transaction_records)').fetchall()]

with open(DATA, 'r', encoding='utf-8') as f:
    rows = json.load(f)

applied = 0
for row in rows:
    cols = [c for c in row.keys() if c in existing_cols]
    placeholders = ','.join('?' for _ in cols)
    sql = 'INSERT OR REPLACE INTO transaction_records (%s) VALUES (%s)' % (','.join(cols), placeholders)
    db.execute(sql, [row[c] for c in cols])
    applied += 1
    print('applied id', row.get('id'), row.get('trans_date'), row.get('amount'))

db.commit()
print('done, applied', applied, 'rows; max id now',
      db.execute('SELECT MAX(id) FROM transaction_records').fetchone()[0])
