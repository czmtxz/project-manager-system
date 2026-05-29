#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print('=== 创建销售出库单明细-运输记录关联表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS sales_item_transport (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sales_item_id INTEGER NOT NULL,
        transport_id INTEGER NOT NULL,
        quantity REAL DEFAULT 0,
        FOREIGN KEY (sales_item_id) REFERENCES sales_order_items(id) ON DELETE CASCADE,
        FOREIGN KEY (transport_id) REFERENCES transport_records(id) ON DELETE CASCADE,
        UNIQUE(sales_item_id, transport_id)
    )
''')
conn.commit()
print('✅ sales_item_transport 表创建成功')

print('\n=== 验证 ===')
cur.execute("SELECT COUNT(*) FROM sales_item_transport")
print(f'关联表记录数: {cur.fetchone()[0]}')

conn.close()
