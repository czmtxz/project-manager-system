# -*- coding: utf-8 -*-
"""为 transport_records 表补充 sales_order_id 列（销售出库运费关联）。"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = sys.argv[1] if len(sys.argv) > 1 else 'project_manager.db'
conn = sqlite3.connect(db_path)
cols = [r[1] for r in conn.execute('PRAGMA table_info(transport_records)').fetchall()]
if 'sales_order_id' not in cols:
    conn.execute('ALTER TABLE transport_records ADD COLUMN sales_order_id INTEGER')
    conn.commit()
    print('Added sales_order_id to transport_records')
else:
    print('sales_order_id already exists')
