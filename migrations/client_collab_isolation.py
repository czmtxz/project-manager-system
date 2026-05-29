# -*- coding: utf-8 -*-
"""客户协同隔离：表结构补丁（可重复执行）"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'project_manager.db'


def run():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    tables_sql = [
        '''CREATE TABLE IF NOT EXISTS client_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            contact_name TEXT,
            company_name TEXT,
            status TEXT DEFAULT 'pending',
            balance REAL DEFAULT 0,
            total_recharge REAL DEFAULT 0,
            total_deduct REAL DEFAULT 0,
            alert_threshold REAL DEFAULT 10,
            last_alert_at TIMESTAMP,
            approved_by INTEGER,
            approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS client_recharges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT,
            payment_no TEXT,
            remark TEXT,
            attachment TEXT,
            status TEXT DEFAULT 'pending',
            confirmed_by INTEGER,
            confirmed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS client_deductions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            sales_order_id INTEGER,
            sales_item_id INTEGER,
            amount REAL NOT NULL,
            quantity REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            item_name TEXT,
            deduct_date DATE,
            remark TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS client_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            title TEXT,
            content TEXT,
            msg_type TEXT DEFAULT 'alert',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
    ]
    for sql in tables_sql:
        c.execute(sql)
    cols = [r[1] for r in c.execute('PRAGMA table_info(sales_orders)')]
    if 'customer_id' not in cols:
        c.execute('ALTER TABLE sales_orders ADD COLUMN customer_id INTEGER')
    user_cols = {
        'status': "TEXT DEFAULT 'active'",
        'real_name': 'TEXT', 'phone': 'TEXT', 'email': 'TEXT',
        'department': 'TEXT', 'last_login': 'TIMESTAMP',
    }
    ucols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
    for col, typ in user_cols.items():
        if col not in ucols:
            c.execute(f'ALTER TABLE users ADD COLUMN {col} {typ}')
    c.execute("UPDATE client_accounts SET status='approved' WHERE status='active'")
    conn.commit()
    conn.close()
    print('client_collab_isolation migration OK')


if __name__ == '__main__':
    run()
