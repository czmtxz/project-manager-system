# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app, get_db

with app.app_context():
    db = get_db()
    row = db.execute(
        "SELECT id FROM client_accounts WHERE status IN ('approved', 'active') LIMIT 1"
    ).fetchone()
    if not row:
        row = db.execute("SELECT id FROM client_accounts LIMIT 1").fetchone()
    cid = row['id'] if row else 1

c = app.test_client()
with c.session_transaction() as s:
    s['client_id'] = cid
    s['client_name'] = 'test'
    s['client_balance'] = 0
    s['client_company_name'] = 'test'
r = c.get('/portal/')
print('status', r.status_code)
if r.status_code != 200:
    print(r.get_data(as_text=True)[:2000])
