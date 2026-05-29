# -*- coding: utf-8 -*-
"""创建客户协同专员内部账号（仅管理客户协同模块）"""
import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'project_manager.db'


def main():
    if len(sys.argv) < 3:
        print('用法: python tools/create_client_collab_user.py <用户名> <密码>')
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]
    hashed = hashlib.md5(password.encode()).hexdigest()
    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            "INSERT INTO users (username, password, role, status) VALUES (?, ?, 'client_collab', 'active')",
            (username, hashed),
        )
    except sqlite3.OperationalError:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, 'client_collab')",
            (username, hashed),
        )
    conn.commit()
    conn.close()
    print(f'已创建客户协同专员: {username}')


if __name__ == '__main__':
    main()
