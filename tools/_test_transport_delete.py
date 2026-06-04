#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/project_manager/project_manager')
from app import app

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    for tid in (83, 84, 85):
        r = c.post(f'/api/transport/{tid}/delete')
        print(tid, r.status_code, r.get_json())
