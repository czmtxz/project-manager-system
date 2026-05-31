#!/usr/bin/env python3
"""Analyze deduction sources for a customer."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "project_manager.db"
cid = 1
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("=== client_deductions by source ===")
rows = db.execute(
    """SELECT cd.id, cd.amount, cd.item_name, cd.sales_order_id, cd.sales_item_id, cd.remark,
              so.order_no, so.remark AS order_remark
       FROM client_deductions cd
       JOIN client_accounts ca ON cd.client_id = ca.id
       LEFT JOIN sales_orders so ON cd.sales_order_id = so.id
       WHERE ca.customer_id=? ORDER BY cd.id""",
    (cid,),
).fetchall()
with_so = [r for r in rows if r['sales_order_id']]
without_so = [r for r in rows if not r['sales_order_id']]
print(f"total deductions: {len(rows)}, with sales_order: {len(with_so)}, without: {len(without_so)}")
for r in without_so[:5]:
    print("  no SO:", dict(r))

print("\n=== delivered sales orders without client_deduction ===")
unsynced = db.execute(
    """SELECT si.id, si.item_name, si.amount, so.order_no, so.status, so.remark
       FROM sales_order_items si
       JOIN sales_orders so ON si.sales_order_id = so.id
       LEFT JOIN client_deductions cd ON cd.sales_item_id = si.id
       WHERE so.customer_id=? AND so.status IN ('delivered','completed')
         AND cd.id IS NULL AND si.amount > 0""",
    (cid,),
).fetchall()
print(f"unsynced items: {len(unsynced)} sum={sum(r['amount'] for r in unsynced):.2f}")
for r in unsynced[:10]:
    print(" ", dict(r))

print("\n=== balance check ===")
acc = db.execute(
    "SELECT id, balance, total_recharge, total_deduct FROM client_accounts WHERE customer_id=? LIMIT 1",
    (cid,),
).fetchone()
rech = db.execute(
    """SELECT COALESCE(SUM(amount),0) FROM client_recharges cr
       JOIN client_accounts ca ON cr.client_id=ca.id
       WHERE ca.customer_id=? AND cr.status='confirmed'""",
    (cid,),
).fetchone()[0]
ded = db.execute(
    """SELECT COALESCE(SUM(amount),0) FROM client_deductions cd
       JOIN client_accounts ca ON cd.client_id=ca.id WHERE ca.customer_id=?""",
    (cid,),
).fetchone()[0]
print(f"stored: balance={acc['balance']} rech={acc['total_recharge']} ded={acc['total_deduct']}")
print(f"computed: rech={rech} ded={ded} balance={rech-ded}")
