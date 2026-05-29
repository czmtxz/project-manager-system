#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print('=== 更新供应商表结构 ===')
new_supplier_cols = [
    ('email', 'TEXT'),
    ('delivery_address', 'TEXT'),
    ('bank_code', 'TEXT'),
    ('invoice_title', 'TEXT'),
    ('invoice_addr_phone', 'TEXT'),
    ('invoice_bank_account', 'TEXT'),
    ('tax_rate', 'REAL'),
]

for col, col_type in new_supplier_cols:
    try:
        cur.execute(f'ALTER TABLE suppliers ADD COLUMN {col} {col_type}')
        print(f'✅ 添加 suppliers.{col}')
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print(f'⏭️  suppliers.{col} 已存在')
        else:
            print(f'⚠️  suppliers.{col}: {e}')

print('\n=== 更新客户表结构 ===')
for col, col_type in new_supplier_cols:
    try:
        cur.execute(f'ALTER TABLE customers ADD COLUMN {col} {col_type}')
        print(f'✅ 添加 customers.{col}')
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print(f'⏭️  customers.{col} 已存在')
        else:
            print(f'⚠️  customers.{col}: {e}')

conn.commit()

print('\n=== 验证 ===')
cur.execute("PRAGMA table_info(suppliers)")
print('供应商表字段:')
for col in cur.fetchall():
    print(f'  - {col[1]} ({col[2]})')

conn.close()
