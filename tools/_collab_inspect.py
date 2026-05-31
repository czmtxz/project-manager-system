# -*- coding: utf-8 -*-
import sqlite3
import os

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

TABLES = ['customers', 'client_accounts', 'client_recharges', 'client_deductions',
          'client_messages', 'client_collab_assignments']


def has_table(t):
    return db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


for t in TABLES:
    if not has_table(t):
        print('%-28s MISSING TABLE' % t)
        continue
    cnt = db.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]
    mx = db.execute('SELECT MAX(id) FROM %s' % t).fetchone()[0]
    print('%-28s count=%-5s max_id=%s' % (t, cnt, mx))

print('--- client_collab users ---')
for r in db.execute("SELECT id, username, role FROM users WHERE role='client_collab'").fetchall():
    print(dict(r))

print('--- client_accounts ---')
if has_table('client_accounts'):
    for r in db.execute("SELECT id, customer_id, username, company_name, status, balance, total_recharge, total_deduct FROM client_accounts ORDER BY id").fetchall():
        print(dict(r))
