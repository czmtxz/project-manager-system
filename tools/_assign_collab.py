# -*- coding: utf-8 -*-
"""把指定客户分配给协同专员（client_collab_assignments）。在服务器上运行。"""
import sqlite3
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db = sqlite3.connect(os.path.join(ROOT, 'project_manager.db'))
db.row_factory = sqlite3.Row

db.execute("""
    CREATE TABLE IF NOT EXISTS client_collab_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, customer_id)
    )
""")

# 给所有 client_collab 专员分配「他们尚未负责、但已是协同客户」的客户
collab_users = [r['id'] for r in db.execute("SELECT id FROM users WHERE role='client_collab' AND status='active'").fetchall()]
client_customers = [r['customer_id'] for r in db.execute(
    "SELECT DISTINCT customer_id FROM client_accounts WHERE customer_id IS NOT NULL").fetchall()]

print('collab users:', collab_users)
print('client customers:', client_customers)

added = 0
for uid in collab_users:
    for cid in client_customers:
        cur = db.execute(
            "INSERT OR IGNORE INTO client_collab_assignments (user_id, customer_id, created_by) VALUES (?, ?, 1)",
            (uid, cid))
        if cur.rowcount:
            added += 1
            print('  assigned user %s -> customer %s' % (uid, cid))
db.commit()
print('added assignments:', added)
print('--- current assignments ---')
for r in db.execute("SELECT user_id, customer_id FROM client_collab_assignments ORDER BY user_id, customer_id").fetchall():
    print(dict(r))
db.close()
