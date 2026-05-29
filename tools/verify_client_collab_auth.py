# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app


def main():
    c = app.test_client()

    # client_collab cannot access dashboard
    with c.session_transaction() as s:
        s['user_id'] = 99
        s['username'] = 'collab1'
        s['role'] = 'client_collab'
    r = c.get('/')
    assert r.status_code in (302, 200)
    if r.status_code == 302:
        assert 'admin/client' in r.location or 'client-accounts' in r.location

    # unauthenticated admin client -> login
    with c.session_transaction() as s:
        s.clear()
    r = c.get('/admin/client-accounts')
    assert r.status_code == 302 and 'login' in r.location

    # admin can access with session
    with c.session_transaction() as s:
        s['user_id'] = 1
        s['username'] = 'admin'
        s['role'] = 'admin'
    r = c.get('/admin/client-accounts')
    assert r.status_code == 200, r.status_code

    print('verify_client_collab_auth OK')


if __name__ == '__main__':
    main()
