# -*- coding: utf-8 -*-
"""将 users.role 中的中文/别名统一为 admin/finance/manager/user（可在服务器执行）。"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from user_access import ROLE_CODE_ALIASES, normalize_staff_role  # noqa: E402

DB = os.environ.get('DATABASE', os.path.join(ROOT, 'project_manager.db'))


def main():
    db = sqlite3.connect(DB)
    rows = db.execute('SELECT id, username, role FROM users').fetchall()
    changed = 0
    for uid, username, role in rows:
        norm = normalize_staff_role(role)
        if norm and norm != (role or '').strip():
            db.execute('UPDATE users SET role=? WHERE id=?', (norm, uid))
            print(f'  {username}: {role!r} -> {norm!r}')
            changed += 1
        elif role and role.strip() in ROLE_CODE_ALIASES:
            norm2 = ROLE_CODE_ALIASES[role.strip()]
            db.execute('UPDATE users SET role=? WHERE id=?', (norm2, uid))
            print(f'  {username}: {role!r} -> {norm2!r}')
            changed += 1
    db.commit()
    print(f'Done. Updated {changed} user(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
