# -*- coding: utf-8 -*-
"""
客户协同内部数据隔离（按内部账号角色 + 负责客户分配）

- admin / finance：全部协同客户
- client_collab：仅分配客户（client_collab_assignments）或本人审核通过的 customer
- manager / user：不可查看协同客户资金（报表与预警均排除）
"""
from flask import session, flash, redirect, url_for

from auth_utils import ROLE_ADMIN, ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN

# 可查看全部协同公司数据的内部角色（协同管理员拥有协同模块全部数据权限）
COLLAB_DATA_ALL_ROLES = frozenset({ROLE_ADMIN, 'finance', ROLE_CLIENT_COLLAB_ADMIN})

# 可访问「客户资金」报表的角色
COLLAB_FUNDS_REPORT_ROLES = frozenset({ROLE_ADMIN, 'finance', ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN})

# 协同专员在报表中心仅开放的 slug
COLLAB_REPORT_SLUGS = frozenset({'client-collab-funds'})


def ensure_collab_scope_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS client_collab_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, customer_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_collab_assign_user
        ON client_collab_assignments(user_id)
    """)


def collab_sees_all_customers(role):
    return role in COLLAB_DATA_ALL_ROLES


def get_assigned_customer_ids(db, user_id, role):
    """
    返回 None 表示不限制（全部客户）；
    返回 list（可为空）表示仅这些 customer_id。
    """
    if not user_id:
        return []
    if collab_sees_all_customers(role):
        return None
    if role != ROLE_CLIENT_COLLAB:
        return []

    ensure_collab_scope_schema(db)
    ids = [
        r['customer_id']
        for r in db.execute(
            'SELECT customer_id FROM client_collab_assignments WHERE user_id=?',
            (user_id,),
        ).fetchall()
        if r['customer_id']
    ]
  # 本人审核通过的客户主数据
    extra = db.execute(
        """SELECT DISTINCT customer_id FROM client_accounts
           WHERE approved_by=? AND customer_id IS NOT NULL""",
        (user_id,),
    ).fetchall()
    for r in extra:
        if r['customer_id'] and r['customer_id'] not in ids:
            ids.append(r['customer_id'])
    return ids


def get_scoped_client_account_ids(db, user_id, role):
    """协同专员可见的 client_accounts.id 列表；None 表示全部。"""
    if collab_sees_all_customers(role):
        return None
    if role != ROLE_CLIENT_COLLAB:
        return []
    customer_ids = get_assigned_customer_ids(db, user_id, role)
    if not customer_ids:
        return []
    ph = ','.join('?' * len(customer_ids))
    rows = db.execute(
        f'SELECT id FROM client_accounts WHERE customer_id IN ({ph})',
        customer_ids,
    ).fetchall()
    return [r['id'] for r in rows]


def can_access_client_account(db, user_id, role, account_id):
    row = db.execute(
        'SELECT customer_id FROM client_accounts WHERE id=?', (account_id,)
    ).fetchone()
    if not row:
        return False
    return can_access_customer(db, user_id, role, row['customer_id'])


def assert_client_account_access(db, user_id, role, account_id):
    """无权限时 flash 并返回 redirect，否则返回 None。"""
    if can_access_client_account(db, user_id, role, account_id):
        return None
    flash('无权操作该客户注册账号', 'danger')
    return redirect(url_for('admin_client_accounts'))


def list_customers_for_collab(db, user_id, role):
    """协同账号可选的客户主数据（管理员全部，专员仅分配客户）。"""
    allowed = get_assigned_customer_ids(db, user_id, role)
    if allowed is None:
        return db.execute(
            "SELECT id, name FROM customers WHERE is_active=1 ORDER BY name"
        ).fetchall()
    if not allowed:
        return []
    ph = ','.join('?' * len(allowed))
    return db.execute(
        f"SELECT id, name FROM customers WHERE is_active=1 AND id IN ({ph}) ORDER BY name",
        allowed,
    ).fetchall()


def can_access_customer(db, user_id, role, customer_id):
    if customer_id is None:
        return False
    allowed = get_assigned_customer_ids(db, user_id, role)
    if allowed is None:
        return True
    try:
        cid = int(customer_id)
    except (TypeError, ValueError):
        return False
    if cid <= 0:
        return False
    return cid in allowed


def assert_customer_access(db, user_id, role, customer_id):
    """无权限时 flash 并返回 redirect response，否则返回 None。"""
    if can_access_customer(db, user_id, role, customer_id):
        return None
    flash('无权访问该客户公司数据', 'danger')
    return redirect(url_for('admin_client_dashboard'))


def filter_company_summaries(companies, allowed_customer_ids):
    if allowed_customer_ids is None:
        return companies
    allowed = set(allowed_customer_ids)
    return [c for c in companies if int(c.get('customer_id') or 0) in allowed]


def list_company_summaries_scoped(db, user_id, role):
    from client_collab_ops import list_company_summaries

    rows = list_company_summaries(db)
    allowed = get_assigned_customer_ids(db, user_id, role)
    return filter_company_summaries(rows, allowed)


def apply_client_account_scope_sql(db, user_id, role, alias='ca'):
    """追加 AND 条件与参数，限制 client_accounts 查询范围。"""
    if collab_sees_all_customers(role):
        return '', []
    if role != ROLE_CLIENT_COLLAB:
        return ' AND 1=0', []

    customer_ids = get_assigned_customer_ids(db, user_id, role)
    if not customer_ids:
        return ' AND 1=0', []

    ph = ','.join('?' * len(customer_ids))
    return f' AND {alias}.customer_id IN ({ph})', list(customer_ids)


def apply_client_id_scope_sql(db, user_id, role, alias='cr'):
    """限制 client_recharges / client_deductions（通过 client_id）。"""
    account_ids = get_scoped_client_account_ids(db, user_id, role)
    if account_ids is None:
        return '', []
    if not account_ids:
        return ' AND 1=0', []
    ph = ','.join('?' * len(account_ids))
    return f' AND {alias}.client_id IN ({ph})', list(account_ids)


def assign_customer_to_user(db, user_id, customer_id, created_by=None):
    if not user_id or not customer_id:
        return
    ensure_collab_scope_schema(db)
    try:
        db.execute(
            """INSERT OR IGNORE INTO client_collab_assignments
               (user_id, customer_id, created_by) VALUES (?, ?, ?)""",
            (user_id, customer_id, created_by),
        )
    except Exception:
        pass


def set_user_assignments(db, user_id, customer_ids, created_by=None):
    """管理员重置某协同专员的负责客户列表。"""
    ensure_collab_scope_schema(db)
    db.execute('DELETE FROM client_collab_assignments WHERE user_id=?', (user_id,))
    for cid in customer_ids:
        if cid:
            assign_customer_to_user(db, user_id, int(cid), created_by)


def get_user_assignments(db, user_id):
    ensure_collab_scope_schema(db)
    return db.execute(
        """SELECT a.customer_id, c.name as customer_name
           FROM client_collab_assignments a
           LEFT JOIN customers c ON a.customer_id = c.id
           WHERE a.user_id=? ORDER BY c.name""",
        (user_id,),
    ).fetchall()


def report_allowed_for_role(slug, role):
    if role in (ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN):
        return slug in COLLAB_REPORT_SLUGS
    if slug == 'client-collab-funds':
        return role in COLLAB_FUNDS_REPORT_ROLES
    return True
