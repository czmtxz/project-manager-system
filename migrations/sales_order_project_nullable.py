# -*- coding: utf-8 -*-
"""使 sales_orders.project_id 可为空（客户协同出库单不归属 ERP 项目）。可重复执行。"""
import os
import sqlite3

DB = os.environ.get('DATABASE', 'project_manager.db')


def project_id_not_null(conn):
    for r in conn.execute("PRAGMA table_info(sales_orders)").fetchall():
        if r[1] == 'project_id':
            return bool(r[3])  # notnull flag
    return False


def main():
    conn = sqlite3.connect(DB)
    if not project_id_not_null(conn):
        print('sales_orders.project_id already nullable, skip')
        conn.close()
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE sales_orders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            contract_id INTEGER,
            order_no TEXT UNIQUE,
            customer_name TEXT,
            order_date DATE,
            delivery_date DATE,
            total_amount REAL DEFAULT 0,
            total_quantity REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            remark TEXT,
            attachment TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            customer_id INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (contract_id) REFERENCES contracts(id)
        );
        INSERT INTO sales_orders_new
            (id, project_id, contract_id, order_no, customer_name, order_date,
             delivery_date, total_amount, total_quantity, status, remark, attachment,
             created_by, created_at, updated_at, customer_id)
        SELECT id, project_id, contract_id, order_no, customer_name, order_date,
               delivery_date, total_amount, total_quantity, status, remark, attachment,
               created_by, created_at, updated_at, customer_id
        FROM sales_orders;
        DROP TABLE sales_orders;
        ALTER TABLE sales_orders_new RENAME TO sales_orders;
        COMMIT;
        """
    )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    conn.close()
    print('sales_orders.project_id is now nullable (rebuilt)')


if __name__ == '__main__':
    main()
