#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/project_manager/project_manager')
from app import app

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    r = c.post('/api/transport/999/delete')
    print('status', r.status_code)
    print('body', r.get_data(as_text=True)[:200])

print('--- routes ---')
for rule in sorted(app.url_map.iter_rules(), key=lambda x: x.rule):
    if 'transport' in rule.rule:
        print(rule.rule, rule.methods)
