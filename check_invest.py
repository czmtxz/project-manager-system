#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('=== 投资记录数据检查 ===')
cur.execute("SELECT id, invest_date, amount, invest_type, participant_id FROM investments ORDER BY id DESC LIMIT 10")
for row in cur.fetchall():
    print(f"ID:{row['id']}, 日期:{row['invest_date']}, 金额:{row['amount']}, 类型:{row['invest_type']}")

print('\n=== 金额统计 ===')
cur.execute("SELECT COUNT(*) as cnt, SUM(amount) as total FROM investments")
row = cur.fetchone()
print(f"记录数: {row['cnt']}, 总金额: {row['total']}")

conn.close()
