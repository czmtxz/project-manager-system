# -*- coding: utf-8 -*-
import re, sqlite3, hashlib, requests

U, P = 'mgr_tmp', 'test1234'
db = sqlite3.connect('project_manager.db'); db.row_factory = sqlite3.Row
db.execute("DELETE FROM users WHERE username=?", (U,))
db.execute("INSERT INTO users (username,password,role,status) VALUES (?,?, 'admin','active')",
           (U, hashlib.md5(P.encode()).hexdigest()))
db.commit()

s = requests.Session()
s.post('http://127.0.0.1:5002/login', data={'username': U, 'password': P})
r = s.get('http://127.0.0.1:5002/admin/client-company/1')
print('workspace status', r.status_code)
print('has edit-recharge btn:', 'edit-recharge' in r.text)
print('has edit-deduction btn:', 'edit-deduction' in r.text)

def state():
    a = db.execute("SELECT balance,total_recharge,total_deduct FROM client_accounts WHERE id=1").fetchone()
    rc = db.execute("SELECT COUNT(*) FROM client_recharges WHERE client_id=1").fetchone()[0]
    dc = db.execute("SELECT COUNT(*) FROM client_deductions WHERE client_id=1").fetchone()[0]
    return dict(a), rc, dc

print('before:', state())
# delete one recharge
rid = db.execute("SELECT id, amount FROM client_recharges WHERE client_id=1 ORDER BY id LIMIT 1").fetchone()
resp = s.post('http://127.0.0.1:5002/admin/client-company/1/recharge/%d/delete' % rid['id'], allow_redirects=False)
print('delete recharge#%d (amount %.2f) -> %d' % (rid['id'], rid['amount'], resp.status_code))
print('after delete recharge:', state())
# delete one deduction
did = db.execute("SELECT id, amount FROM client_deductions WHERE client_id=1 ORDER BY id LIMIT 1").fetchone()
resp = s.post('http://127.0.0.1:5002/admin/client-company/1/deduction/%d/delete' % did['id'], allow_redirects=False)
print('delete deduction#%d (amount %.2f) -> %d' % (did['id'], did['amount'], resp.status_code))
print('after delete deduction:', state())

db.execute("DELETE FROM users WHERE username=?", (U,)); db.commit(); db.close()
print('cleaned temp admin')
