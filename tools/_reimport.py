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

from openpyxl import load_workbook
from client_collab_ops import parse_collab_excel, import_standard_excel_bundle

EXCEL = sys.argv[1]
CLIENT_ID = 1
CUSTOMER_ID = 1
NAME_PREFIX = '虎子'  # 仅导入可见的「虎子」页签（跳过隐藏、景鸿、空表）

wb = load_workbook(EXCEL, read_only=True)
TARGET_SHEETS = [ws.title for ws in wb.worksheets
                 if ws.sheet_state == 'visible' and ws.title.startswith(NAME_PREFIX)]
wb.close()
print('target sheets:', TARGET_SHEETS)

db = sqlite3.connect(os.path.join(ROOT, 'project_manager.db'))
db.row_factory = sqlite3.Row

# 同时清理由出库导入生成的客户协同出库单(CC*)及其明细，避免残留
old_orders = [r['id'] for r in db.execute(
    "SELECT so.id FROM sales_orders so WHERE so.customer_id=? AND so.order_no LIKE 'CC%'", (CUSTOMER_ID,)).fetchall()]
db.execute("DELETE FROM client_recharges WHERE client_id=?", (CLIENT_ID,))
db.execute("DELETE FROM client_deductions WHERE client_id=?", (CLIENT_ID,))
db.execute("DELETE FROM client_messages WHERE client_id=? AND title='充值到账'", (CLIENT_ID,))
for oid in old_orders:
    db.execute("DELETE FROM sales_order_items WHERE order_id=?", (oid,))
    db.execute("DELETE FROM sales_orders WHERE id=?", (oid,))
db.execute("UPDATE client_accounts SET balance=0, total_recharge=0, total_deduct=0 WHERE id=?", (CLIENT_ID,))
db.commit()
print('cleared old recharges/deductions and %d CC sales orders; balance reset' % len(old_orders))

for sn in TARGET_SHEETS:
    parsed = parse_collab_excel(EXCEL, mode='standard', sheet=sn)
    if parsed.get('error'):
        print('SKIP %r: %s' % (sn, parsed['error']))
        continue
    ok, msg, errs = import_standard_excel_bundle(db, CUSTOMER_ID, CLIENT_ID, parsed, user_id=1, split_orders=False)
    print('%r -> ok=%s | %s' % (sn, ok, msg))
    if errs:
        print('   errs:', errs[:3])
db.commit()

acc = db.execute("SELECT balance, total_recharge, total_deduct FROM client_accounts WHERE id=?", (CLIENT_ID,)).fetchone()
rc = db.execute("SELECT COUNT(*) FROM client_recharges WHERE client_id=?", (CLIENT_ID,)).fetchone()[0]
dc = db.execute("SELECT COUNT(*) FROM client_deductions WHERE client_id=?", (CLIENT_ID,)).fetchone()[0]
print('=== RESULT ===')
print('recharges:', rc, '| deductions:', dc)
print('balance: %.2f | total_recharge: %.2f | total_deduct: %.2f' % (acc['balance'], acc['total_recharge'], acc['total_deduct']))
db.close()
