# -*- coding: utf-8 -*-
"""校验各角色功能权限（本地 SQLite）。"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from user_access import (  # noqa: E402
    has_permission,
    normalize_staff_role,
    get_effective_permissions,
    user_is_admin,
)

DB = os.environ.get('DATABASE', os.path.join(ROOT, 'project_manager.db'))


def main():
    if not os.path.isfile(DB):
        print('DB not found:', DB)
        return 1
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    checks = [
        ('admin', 'purchase.view'),
        ('finance', 'sales.view'),
        ('超级管理员', 'purchase.view'),
        ('manager', 'purchase.view'),
    ]
    ok = True
    for role, code in checks:
        eff = get_effective_permissions(db, 1, role)
        allowed = has_permission(db, 1, role, code)
        norm = normalize_staff_role(role)
        print(f'role={role!r} -> {norm!r}  {code}={allowed}  admin={user_is_admin(role)}  count={len(eff)}')
        if role in ('admin', '超级管理员') and not allowed:
            ok = False
    users = db.execute('SELECT id, username, role FROM users LIMIT 20').fetchall()
    print('--- users ---')
    for u in users:
        role = u['role']
        print(
            f"  id={u['id']} {u['username']} role={role!r} norm={normalize_staff_role(role)!r} "
            f"sales.view={has_permission(db, u['id'], role, 'sales.view')}"
        )
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
