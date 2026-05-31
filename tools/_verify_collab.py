# -*- coding: utf-8 -*-
"""验证协同专员 zxl 能看到哪些客户账户（使用 app 自身的范围逻辑）。"""
import sqlite3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
db = sqlite3.connect(os.path.join(ROOT, 'project_manager.db'))
db.row_factory = sqlite3.Row

print('assignments:', [dict(r) for r in db.execute(
    'SELECT user_id, customer_id FROM client_collab_assignments').fetchall()])

from client_collab_scope import get_scoped_client_account_ids, get_assigned_customer_ids

uid, role = 11, 'client_collab'
print('zxl assigned customer_ids:', get_assigned_customer_ids(db, uid, role))
acct_ids = get_scoped_client_account_ids(db, uid, role)
print('zxl visible client_account ids:', acct_ids)
if acct_ids:
    ph = ','.join('?' * len(acct_ids))
    for r in db.execute('SELECT id, username, company_name, status FROM client_accounts WHERE id IN (%s)' % ph, acct_ids).fetchall():
        print('  ->', dict(r))
db.close()
