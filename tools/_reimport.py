# -*- coding: utf-8 -*-
"""清空客户(默认id=1)的充值/扣减并按正确识别重新导入指定页签。
用法: python _reimport.py <excel_path>
导入页签：索引 0(虎子) 与 3(虎子 (4))，跳过隐藏/重复/景鸿。
"""
import sys
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pandas as pd
from client_collab_ops import parse_collab_excel, import_standard_excel_bundle

EXCEL = sys.argv[1]
CLIENT_ID = 1
CUSTOMER_ID = 1
TARGET_INDICES = [0, 3]

db = sqlite3.connect(os.path.join(ROOT, 'project_manager.db'))
db.row_factory = sqlite3.Row

# 1) 清空错误数据并归零
before = db.execute("SELECT COUNT(*) FROM client_recharges WHERE client_id=?", (CLIENT_ID,)).fetchone()[0]
db.execute("DELETE FROM client_recharges WHERE client_id=?", (CLIENT_ID,))
db.execute("DELETE FROM client_deductions WHERE client_id=?", (CLIENT_ID,))
db.execute("UPDATE client_accounts SET balance=0, total_recharge=0, total_deduct=0 WHERE id=?", (CLIENT_ID,))
db.commit()
print('cleared %d old recharges; balance reset to 0' % before)

# 2) 重新导入目标页签
sheet_names = list(pd.ExcelFile(EXCEL).sheet_names)
for idx in TARGET_INDICES:
    if idx >= len(sheet_names):
        continue
    sn = sheet_names[idx]
    parsed = parse_collab_excel(EXCEL, mode='standard', sheet=sn)
    if parsed.get('error'):
        print('SKIP idx %d (%r): %s' % (idx, sn, parsed['error']))
        continue
    ok, msg, errs = import_standard_excel_bundle(db, CUSTOMER_ID, CLIENT_ID, parsed, user_id=1, split_orders=False)
    print('idx %d %r -> ok=%s | %s' % (idx, sn, ok, msg))
    if errs:
        print('   errs:', errs[:3])
db.commit()

# 3) 结果
acc = db.execute("SELECT balance, total_recharge, total_deduct FROM client_accounts WHERE id=?", (CLIENT_ID,)).fetchone()
rc = db.execute("SELECT COUNT(*) FROM client_recharges WHERE client_id=?", (CLIENT_ID,)).fetchone()[0]
dc = db.execute("SELECT COUNT(*) FROM client_deductions WHERE client_id=?", (CLIENT_ID,)).fetchone()[0]
print('=== RESULT ===')
print('recharges:', rc, '| deductions:', dc)
print('balance: %.2f | total_recharge: %.2f | total_deduct: %.2f' % (acc['balance'], acc['total_recharge'], acc['total_deduct']))
db.close()
