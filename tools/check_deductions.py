# -*- coding: utf-8 -*-
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else 'project_manager.db'
cid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """SELECT cd.id, cd.deduct_date, cd.item_name, cd.quantity, cd.unit_price, cd.amount
       FROM client_deductions cd
       JOIN client_accounts ca ON cd.client_id = ca.id
       WHERE ca.customer_id=?
       ORDER BY cd.id""",
    (cid,),
).fetchall()
print('total deductions', len(rows))
zero = [r for r in rows if float(r['unit_price'] or 0) <= 0 and float(r['amount'] or 0) <= 0]
print('zero price and amount', len(zero))
zero_price = [r for r in rows if float(r['unit_price'] or 0) <= 0]
print('zero unit_price (any amount)', len(zero_price))
zero_amount = [r for r in rows if float(r['amount'] or 0) <= 0]
print('zero amount (any price)', len(zero_amount))
for r in zero_amount[:15]:
    print(dict(r))
rech = conn.execute(
    "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM client_recharges cr JOIN client_accounts ca ON cr.client_id=ca.id WHERE ca.customer_id=?",
    (cid,),
).fetchone()
print('recharges', rech[0], 'sum', rech[1])
ded = conn.execute(
    "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM client_deductions cd JOIN client_accounts ca ON cd.client_id=ca.id WHERE ca.customer_id=?",
    (cid,),
).fetchone()
print('deductions', ded[0], 'sum', ded[1])
conn.close()
