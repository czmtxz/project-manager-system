# -*- coding: utf-8 -*-
import sqlite3, os
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
print('client_accounts:')
for r in db.execute("SELECT id, customer_id, username, company_name, status, balance, total_recharge, total_deduct FROM client_accounts").fetchall():
    print(' ', dict(r))
print('client_recharges count:', db.execute("SELECT COUNT(*) FROM client_recharges").fetchone()[0])
print('client_deductions count:', db.execute("SELECT COUNT(*) FROM client_deductions").fetchone()[0])
print('customers:')
for r in db.execute("SELECT id, name FROM customers").fetchall():
    print(' ', dict(r))
db.close()
