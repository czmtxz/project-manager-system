# -*- coding: utf-8 -*-
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else 'project_manager.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT status, COUNT(*), COALESCE(SUM(amount),0) FROM client_recharges GROUP BY status"
).fetchall()
print('by status:')
for r in rows:
    print(dict(r))
pending = conn.execute(
    """SELECT cr.id, cr.amount, cr.status, ca.company_name, ca.customer_id
       FROM client_recharges cr JOIN client_accounts ca ON cr.client_id=ca.id
       WHERE cr.status='pending'"""
).fetchall()
print('pending rows', len(pending))
for r in pending:
    print(dict(r))
