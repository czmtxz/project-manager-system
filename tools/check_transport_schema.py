# -*- coding: utf-8 -*-
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else 'project_manager.db'
conn = sqlite3.connect(db_path)
cols = [r[1] for r in conn.execute('PRAGMA table_info(transport_records)').fetchall()]
print('transport_records columns:', cols)
print('has sales_order_id:', 'sales_order_id' in cols)
