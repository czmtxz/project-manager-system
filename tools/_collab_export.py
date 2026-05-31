# -*- coding: utf-8 -*-
"""导出服务器客户协同相关数据到 JSON（含被引用的 customers / client_collab 用户）。"""
import sqlite3
import os
import json

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

COLLAB_TABLES = ['client_accounts', 'client_recharges', 'client_deductions',
                 'client_messages', 'client_collab_assignments']


def has_table(t):
    return db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


out = {'tables': {}, 'customers': [], 'collab_users': []}

cust_ids = set()
user_ids = set()
for t in COLLAB_TABLES:
    if not has_table(t):
        out['tables'][t] = []
        continue
    rows = [dict(r) for r in db.execute('SELECT * FROM %s' % t).fetchall()]
    out['tables'][t] = rows
    for r in rows:
        if r.get('customer_id'):
            cust_ids.add(r['customer_id'])
        if r.get('user_id'):
            user_ids.add(r['user_id'])
        if r.get('confirmed_by'):
            user_ids.add(r['confirmed_by'])
        if r.get('approved_by'):
            user_ids.add(r['approved_by'])

# 被引用到的客户
if cust_ids and has_table('customers'):
    q = 'SELECT * FROM customers WHERE id IN (%s)' % ','.join('?' * len(cust_ids))
    out['customers'] = [dict(r) for r in db.execute(q, tuple(cust_ids)).fetchall()]

# 客户协同专员账号
out['collab_users'] = [dict(r) for r in db.execute("SELECT * FROM users WHERE role='client_collab'").fetchall()]

dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_collab_data.json')
with open(dest, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)

print('exported to', dest)
for t in COLLAB_TABLES:
    print('  %-28s %d rows' % (t, len(out['tables'].get(t, []))))
print('  customers referenced        ', len(out['customers']), [c.get('id') for c in out['customers']])
print('  collab users                ', len(out['collab_users']), [(u.get('id'), u.get('username')) for u in out['collab_users']])
