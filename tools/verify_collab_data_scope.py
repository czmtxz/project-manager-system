# -*- coding: utf-8 -*-
"""验证客户协同数据隔离"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app
from client_collab_scope import ensure_collab_scope_schema, set_user_assignments


def main():
    c = app.test_client()
    db = app.test_client().application.app_context()
    with app.app_context():
        from app import get_db
        g_db = get_db()
        ensure_collab_scope_schema(g_db)

    # collab blocked from full reports hub content
    with c.session_transaction() as s:
        s['user_id'] = 99
        s['username'] = 'collab1'
        s['role'] = 'client_collab'
    r = c.get('/reports/executive-overview')
    assert r.status_code == 302
    r = c.get('/reports/client-collab-funds')
    assert r.status_code == 200

    # manager cannot open client funds report
    with c.session_transaction() as s:
        s['user_id'] = 2
        s['role'] = 'manager'
    r = c.get('/reports/client-collab-funds')
    assert r.status_code == 302

    # finance can
    with c.session_transaction() as s:
        s['user_id'] = 3
        s['role'] = 'finance'
    r = c.get('/reports/client-collab-funds')
    assert r.status_code == 200

    print('verify_collab_data_scope OK')


if __name__ == '__main__':
    main()
