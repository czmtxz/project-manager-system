# -*- coding: utf-8 -*-
"""客户协同门户：租户（customer_id）数据隔离"""
from datetime import datetime

CLIENT_STATUS_PENDING = 'pending'
CLIENT_STATUS_APPROVED = 'approved'
CLIENT_STATUS_REJECTED = 'rejected'
CLIENT_STATUS_DISABLED = 'disabled'


def table_has_column(db, table, column):
    cols = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def ensure_schema_extensions(db):
    """运行时补齐客户协同相关字段（幂等）。"""
    cur = db.cursor()
    if not table_has_column(db, 'sales_orders', 'customer_id'):
        cur.execute("ALTER TABLE sales_orders ADD COLUMN customer_id INTEGER")
    user_cols = {
        'real_name': 'TEXT', 'phone': 'TEXT', 'email': 'TEXT',
        'department': 'TEXT', 'status': "TEXT DEFAULT 'active'",
        'last_login': 'TIMESTAMP',
    }
    for col, typ in user_cols.items():
        if not table_has_column(db, 'users', col):
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
    db.commit()


def resolve_or_create_customer(db, company_name, contact_name='', phone=''):
    name = (company_name or '').strip()
    if not name:
        return None
    row = db.execute(
        "SELECT id FROM customers WHERE name=?", (name,)
    ).fetchone()
    if row:
        return row['id']
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if table_has_column(db, 'customers', 'updated_at'):
        cur = db.execute(
            """INSERT INTO customers (name, contact, phone, remark, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (name, contact_name or '', phone or '', '客户协同门户自动创建', now, now),
        )
    else:
        cur = db.execute(
            """INSERT INTO customers (name, contact, phone, remark, is_active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (name, contact_name or '', phone or '', '客户协同门户自动创建', now),
        )
    db.commit()
    return cur.lastrowid


def normalize_client_status(status):
    if status == 'active':
        return CLIENT_STATUS_APPROVED
    return status


def get_client_by_id(db, client_id):
    row = db.execute("SELECT * FROM client_accounts WHERE id=?", (client_id,)).fetchone()
    if row:
        return dict(row)
    return None


def client_ids_for_customer(db, customer_id, include_disabled=False):
    if not customer_id:
        return []
    if include_disabled:
        q = "SELECT id FROM client_accounts WHERE customer_id=?"
    else:
        q = (
            "SELECT id FROM client_accounts WHERE customer_id=? "
            "AND status IN ('approved', 'active')"
        )
    rows = db.execute(q, (customer_id,)).fetchall()
    return [r['id'] for r in rows]


def company_scope_client_ids(db, client):
    """同公司下所有门户账号 ID（共享流水/出库视图）。"""
    cid = client.get('customer_id') if isinstance(client, dict) else client['customer_id']
    if cid:
        ids = client_ids_for_customer(db, cid)
        if ids:
            return ids
    return [client['id'] if isinstance(client, dict) else client['id']]


def sales_order_customer_filter(client):
    """返回 (sql_fragment, params) 用于 WHERE。"""
    if client.get('customer_id'):
        return 'so.customer_id = ?', (client['customer_id'],)
    return 'so.customer_name = ?', (client.get('company_name') or '',)


def assert_sales_order_access(db, client, order_id):
    sql_extra, params = sales_order_customer_filter(client)
    row = db.execute(
        f"SELECT so.id FROM sales_orders so WHERE so.id=? AND {sql_extra}",
        (order_id,) + params,
    ).fetchone()
    return row is not None


def aggregate_company_balance(db, client):
    """同 customer 下账户余额合计。"""
    ids = company_scope_client_ids(db, client)
    if not ids:
        return 0.0, 0.0, 0.0
    ph = ','.join('?' * len(ids))
    row = db.execute(
        f"""SELECT COALESCE(SUM(balance),0) as bal,
                   COALESCE(SUM(total_recharge),0) as rech,
                   COALESCE(SUM(total_deduct),0) as ded
            FROM client_accounts WHERE id IN ({ph})""",
        ids,
    ).fetchone()
    return float(row['bal']), float(row['rech']), float(row['ded'])


def build_portal_transactions(db, client, tx_type='', start_date='', end_date=''):
    """合并充值与扣减流水。"""
    ids = company_scope_client_ids(db, client)
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    rows = []

    if tx_type in ('', 'recharge'):
        q = f"""SELECT created_at, 'recharge' as type, amount,
                       payment_method as remark, status, id,
                       NULL as balance_after, client_id
                FROM client_recharges
                WHERE client_id IN ({ph}) AND status='confirmed'"""
        params = list(ids)
        if start_date:
            q += " AND date(created_at) >= ?"
            params.append(start_date)
        if end_date:
            q += " AND date(created_at) <= ?"
            params.append(end_date)
        for r in db.execute(q, params).fetchall():
            rows.append(dict(r))

    if tx_type in ('', 'deduction'):
        q = f"""SELECT created_at, 'deduction' as type, amount,
                       COALESCE(item_name, remark) as remark,
                       'confirmed' as status, id,
                       NULL as balance_after, client_id
                FROM client_deductions
                WHERE client_id IN ({ph})"""
        params = list(ids)
        if start_date:
            q += " AND date(COALESCE(deduct_date, created_at)) >= ?"
            params.append(start_date)
        if end_date:
            q += " AND date(COALESCE(deduct_date, created_at)) <= ?"
            params.append(end_date)
        for r in db.execute(q, params).fetchall():
            rows.append(dict(r))

    rows.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    bal, _, _ = aggregate_company_balance(db, client)
    running = bal
    for r in rows:
        r['balance_after'] = running
        if r['type'] == 'recharge':
            running -= float(r['amount'] or 0)
        else:
            running += float(r['amount'] or 0)
    total_recharge = sum(float(r['amount'] or 0) for r in rows if r['type'] == 'recharge')
    total_deduction = sum(float(r['amount'] or 0) for r in rows if r['type'] == 'deduction')
    return rows, bal, total_recharge, total_deduction


def sync_deductions_for_customer(db, customer_id=None):
    """按 customer_id 同步出库扣减（管理端）。"""
    sql = """SELECT si.id as sales_item_id, si.sales_order_id, si.item_name,
                    si.quantity, si.unit_price, si.amount,
                    so.customer_id, so.customer_name, so.order_no
             FROM sales_order_items si
             JOIN sales_orders so ON si.sales_order_id = so.id
             LEFT JOIN client_deductions cd ON cd.sales_item_id = si.id
             WHERE so.status IN ('delivered', 'completed') AND cd.id IS NULL
             AND si.quantity > 0"""
    params = []
    if customer_id:
        sql += " AND so.customer_id=?"
        params.append(customer_id)
    items = db.execute(sql, params).fetchall()
    count = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for item in items:
        client = None
        if item['customer_id']:
            client = db.execute(
                """SELECT id FROM client_accounts
                   WHERE customer_id=? AND status IN ('approved', 'active')
                   ORDER BY id LIMIT 1""",
                (item['customer_id'],),
            ).fetchone()
        if not client and item['customer_name']:
            client = db.execute(
                """SELECT id FROM client_accounts
                   WHERE company_name=? AND status IN ('approved', 'active')
                   ORDER BY id LIMIT 1""",
                (item['customer_name'],),
            ).fetchone()
        if not client:
            continue
        existing = db.execute(
            "SELECT id FROM client_deductions WHERE sales_item_id=?",
            (item['sales_item_id'],),
        ).fetchone()
        if existing:
            continue
        db.execute(
            """INSERT INTO client_deductions
               (client_id, sales_order_id, sales_item_id, amount, quantity,
                unit_price, item_name, deduct_date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client['id'], item['sales_order_id'], item['sales_item_id'],
             item['amount'], item['quantity'], item['unit_price'],
             item['item_name'], now[:10], now),
        )
        db.execute(
            """UPDATE client_accounts
               SET total_deduct=total_deduct+?, balance=balance-?, updated_at=?
               WHERE id=?""",
            (item['amount'], item['amount'], now, client['id']),
        )
        count += 1
    return count
