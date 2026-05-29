#!/usr/bin/env python3
import sqlite3, os

DB = '/opt/project_manager/project_manager/project_manager.db'

def q(sql):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql)
    result = cur.fetchall()
    conn.commit()
    conn.close()
    return result

print('=== 查找业务招待费分类ID ===')
result = q("SELECT id, code, name FROM categories WHERE name LIKE '%业务招待%' OR name LIKE '%招待%' LIMIT 5")
for r in result:
    print(f"ID: {r['id']}, 编码: {r['code']}, 名称: {r['name']}")

print('\n=== 当前收支记录分类统计 ===')
result = q("""
SELECT c.name, COUNT(*) as count 
FROM transaction_records t 
LEFT JOIN categories c ON t.category_id = c.id 
GROUP BY c.name 
ORDER BY count DESC
""")
for r in result:
    print(f"{r['name'] or '未分类'}: {r['count']}条")

print('\n=== 更新所有记录分类为业务招待费 ===')
# 先获取业务招待费的ID
biz = q("SELECT id FROM categories WHERE name = '业务招待费' LIMIT 1")
if biz:
    biz_id = biz[0]['id']
    print(f'业务招待费ID: {biz_id}')
    q(f"UPDATE transaction_records SET category_id = {biz_id}")
    print('✅ 已更新所有记录')
else:
    print('❌ 未找到业务招待费分类，请检查分类名称')

print('\n=== 更新后分类统计 ===')
result = q("""
SELECT c.name, COUNT(*) as count 
FROM transaction_records t 
LEFT JOIN categories c ON t.category_id = c.id 
GROUP BY c.name 
ORDER BY count DESC
""")
for r in result:
    print(f"{r['name'] or '未分类'}: {r['count']}条")
