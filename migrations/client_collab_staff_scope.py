# -*- coding: utf-8 -*-
"""协同专员负责客户分配表（数据隔离）"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'project_manager.db'


def run():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_collab_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, customer_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_collab_assign_user
        ON client_collab_assignments(user_id)
    """)
    conn.commit()
    conn.close()
    print('client_collab_staff_scope migration OK')


if __name__ == '__main__':
    run()
