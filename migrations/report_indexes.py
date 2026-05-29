# -*- coding: utf-8 -*-
"""报表查询常用字段索引（可重复执行）"""
import os
import sqlite3

DB = os.environ.get('DATABASE', 'project_manager.db')

INDEXES = [
    'CREATE INDEX IF NOT EXISTS idx_trans_project_date ON transaction_records(project_id, trans_date)',
    'CREATE INDEX IF NOT EXISTS idx_sales_order_date ON sales_orders(project_id, order_date)',
    'CREATE INDEX IF NOT EXISTS idx_sales_pay_date ON sales_payments(project_id, payment_date)',
    'CREATE INDEX IF NOT EXISTS idx_purchase_date ON purchase_orders(project_id, purchase_date)',
    'CREATE INDEX IF NOT EXISTS idx_invoice_date ON invoices(project_id, invoice_date)',
    'CREATE INDEX IF NOT EXISTS idx_contract_project ON contracts(project_id)',
    'CREATE INDEX IF NOT EXISTS idx_recharge_created ON client_recharges(created_at)',
    'CREATE INDEX IF NOT EXISTS idx_deduction_date ON client_deductions(deduct_date)',
]


def main():
    conn = sqlite3.connect(DB)
    for sql in INDEXES:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if 'no such column' in str(e).lower():
                alt = sql.replace('purchase_date', 'order_date')
                try:
                    conn.execute(alt)
                except sqlite3.OperationalError:
                    print('skip:', sql[:60], e)
            else:
                print('skip:', sql[:60], e)
    conn.commit()
    conn.close()
    print('report indexes ok')


if __name__ == '__main__':
    main()
