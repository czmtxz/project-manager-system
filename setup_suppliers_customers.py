#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print('=== 创建供应商表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        contact TEXT,
        phone TEXT,
        address TEXT,
        bank_name TEXT,
        bank_account TEXT,
        tax_no TEXT,
        remark TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()
print('✅ suppliers 表创建成功')

print('\n=== 创建客户表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        contact TEXT,
        phone TEXT,
        address TEXT,
        bank_name TEXT,
        bank_account TEXT,
        tax_no TEXT,
        remark TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()
print('✅ customers 表创建成功')

# 从现有采购单中提取供应商名称
print('\n=== 从现有采购单提取供应商 ===')
cur.execute("SELECT DISTINCT supplier_name FROM purchase_orders WHERE supplier_name IS NOT NULL AND supplier_name != ''")
suppliers = cur.fetchall()
for s in suppliers:
    name = s[0].strip()
    if name:
        try:
            cur.execute("INSERT OR IGNORE INTO suppliers (name) VALUES (?)", (name,))
        except:
            pass
conn.commit()
print(f'✅ 提取了 {len(suppliers)} 个供应商')

# 从现有销售出库单中提取客户名称
print('\n=== 从现有销售出库单提取客户 ===')
cur.execute("SELECT DISTINCT customer_name FROM sales_orders WHERE customer_name IS NOT NULL AND customer_name != ''")
customers = cur.fetchall()
for c in customers:
    name = c[0].strip()
    if name:
        try:
            cur.execute("INSERT OR IGNORE INTO customers (name) VALUES (?)", (name,))
        except:
            pass
conn.commit()
print(f'✅ 提取了 {len(customers)} 个客户')

print('\n=== 验证 ===')
cur.execute("SELECT COUNT(*) FROM suppliers")
print(f'供应商总数: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM customers")
print(f'客户总数: {cur.fetchone()[0]}')

conn.close()
