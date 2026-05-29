#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print('=== 创建运输记录-采购明细关联表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS transport_purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transport_id INTEGER NOT NULL,
        purchase_item_id INTEGER NOT NULL,
        quantity REAL DEFAULT 0,
        FOREIGN KEY (transport_id) REFERENCES transport_records(id) ON DELETE CASCADE,
        FOREIGN KEY (purchase_item_id) REFERENCES purchase_items(id) ON DELETE CASCADE,
        UNIQUE(transport_id, purchase_item_id)
    )
''')
conn.commit()
print('✅ transport_purchase_items 表创建成功')

# 迁移现有数据：将transport_records中的purchase_item_id复制到关联表
print('\n=== 迁移现有数据 ===')
cur.execute("""
    INSERT OR IGNORE INTO transport_purchase_items (transport_id, purchase_item_id, quantity)
    SELECT id, purchase_item_id, quantity FROM transport_records 
    WHERE purchase_item_id IS NOT NULL
""")
migrated = cur.rowcount
conn.commit()
print(f'✅ 迁移了 {migrated} 条现有关联数据')

print('\n=== 验证 ===')
cur.execute("SELECT COUNT(*) FROM transport_purchase_items")
print(f'关联表记录数: {cur.fetchone()[0]}')

conn.close()
