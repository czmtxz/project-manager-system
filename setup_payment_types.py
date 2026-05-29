#!/usr/bin/env python3
import sqlite3, os

DB = '/opt/project_manager/project_manager/project_manager.db'

def q(sql):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    conn.close()

print('=== 创建付款类型表 ===')
try:
    q("""
    CREATE TABLE IF NOT EXISTS payment_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    print('✅ payment_types 表创建成功')
except Exception as e:
    print(f'创建表失败: {e}')

print('\n=== 添加默认数据 ===')
defaults = ['砂石料', '运费']
for name in defaults:
    try:
        q(f"INSERT INTO payment_types (name) VALUES ('{name}')")
        print(f'✅ 添加: {name}')
    except Exception as e:
        print(f'添加 {name} 失败(可能已存在): {e}')

print('\n=== 查看当前付款类型 ===')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM payment_types ORDER BY id")
for row in cur.fetchall():
    print(f"ID: {row['id']}, 名称: {row['name']}")
conn.close()

print('\n=== 检查payments表是否有payment_type字段 ===')
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("PRAGMA table_info(payments)")
cols = [row[1] for row in cur.fetchall()]
conn.close()
if 'payment_type' not in cols:
    print('添加 payment_type 字段到 payments 表')
    q("ALTER TABLE payments ADD COLUMN payment_type TEXT")
    print('✅ payment_type 字段已添加')
else:
    print('payment_type 字段已存在')
