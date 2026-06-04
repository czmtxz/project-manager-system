#!/usr/bin/env python3
import sys
import re
sys.path.insert(0, '/opt/project_manager/project_manager')
from app import app

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    r = c.get('/sales/order/14')
    html = r.get_data(as_text=True)
    print('status', r.status_code, 'len', len(html))
    for pat in [
        r"onclick=\"deleteTransport\(\d+\)\"",
        r'/api/transport/\$\{id\}/delete',
        r'/api/sales/transport/',
        r'function deleteTransport',
    ]:
        m = re.search(pat, html)
        print(pat, '->', bool(m), m.group(0)[:80] if m else '')
