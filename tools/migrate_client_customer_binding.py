# -*- coding: utf-8 -*-
"""回填 client_accounts.customer_id 与 sales_orders.customer_id"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'project_manager.db'


def ensure_column(conn, table, col, col_def):
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
    if col not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_def}')
        print(f'  + {table}.{col}')


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_column(conn, 'sales_orders', 'customer_id', 'INTEGER')
    cur = conn.cursor()

    created = 0
    for row in cur.execute(
        "SELECT DISTINCT company_name FROM client_accounts "
        "WHERE company_name IS NOT NULL AND company_name != ''"
    ):
        name = row[0].strip()
        cust = cur.execute(
            "SELECT id FROM customers WHERE name=?", (name,)
        ).fetchone()
        if not cust:
            cur.execute(
                "INSERT INTO customers (name, remark, is_active) VALUES (?, ?, 1)",
                (name, '迁移脚本自动创建'),
            )
            created += 1
            cust_id = cur.lastrowid
        else:
            cust_id = cust[0]
        cur.execute(
            "UPDATE client_accounts SET customer_id=? "
            "WHERE company_name=? AND (customer_id IS NULL OR customer_id=0)",
            (cust_id, name),
        )

    for row in cur.execute(
        "SELECT id, customer_name FROM sales_orders "
        "WHERE customer_name IS NOT NULL AND customer_name != '' "
        "AND (customer_id IS NULL OR customer_id=0)"
    ):
        cust = cur.execute(
            "SELECT id FROM customers WHERE name=?", (row[1],)
        ).fetchone()
        if cust:
            cur.execute(
                "UPDATE sales_orders SET customer_id=? WHERE id=?",
                (cust[0], row[0]),
            )

    cur.execute(
        "UPDATE client_accounts SET status='approved' WHERE status='active'"
    )
    conn.commit()
    print(f'customers created: {created}')
    print('migration done')
    conn.close()


if __name__ == '__main__':
    main()
