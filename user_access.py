# -*- coding: utf-8 -*-
"""用户功能权限与项目数据权限（按项目授权）。"""

from flask import session, flash, redirect, url_for

from auth_utils import COLLAB_ONLY_ROLES, ROLE_ADMIN

# 功能权限定义：(code, 名称, 分组)
PERMISSION_DEFS = [
    ('project.view', '查看项目', '项目'),
    ('project.create', '新建项目', '项目'),
    ('project.edit', '编辑项目', '项目'),
    ('project.delete', '删除项目', '项目'),
    ('transaction.view', '查看费用', '费用'),
    ('transaction.create', '录入费用', '费用'),
    ('transaction.edit', '编辑费用', '费用'),
    ('purchase.view', '查看采购', '采购销售'),
    ('purchase.edit', '编辑采购', '采购销售'),
    ('sales.view', '查看销售', '采购销售'),
    ('sales.edit', '编辑销售', '采购销售'),
    ('contract.view', '查看合同', '合同发票'),
    ('invoice.view', '查看发票', '合同发票'),
    ('invoice.edit', '编辑发票', '合同发票'),
    ('report.view', '查看报表', '报表'),
    ('report.export', '导出报表', '报表'),
    ('account.manage', '账号管理', '系统'),
    ('backup.manage', '备份与数据', '系统'),
]

ALL_PERMISSION_CODES = frozenset(p[0] for p in PERMISSION_DEFS)

ROLE_DEFAULT_PERMISSIONS = {
    'admin': ALL_PERMISSION_CODES,
    'finance': ALL_PERMISSION_CODES - frozenset({'account.manage', 'backup.manage', 'project.delete'}),
    'manager': frozenset({
        'project.view', 'project.create', 'project.edit',
        'transaction.view', 'transaction.create', 'transaction.edit',
        'purchase.view', 'purchase.edit', 'sales.view', 'sales.edit',
        'contract.view', 'invoice.view', 'invoice.edit',
        'report.view', 'report.export',
    }),
    'user': frozenset({
        'project.view', 'transaction.view', 'transaction.create',
        'purchase.view', 'sales.view', 'contract.view', 'invoice.view', 'report.view',
    }),
    'client_collab': frozenset(),
    'client_collab_admin': frozenset({'report.view'}),
}

# 可访问全部项目的角色
PROJECT_ALL_ROLES = frozenset({ROLE_ADMIN, 'finance'})

# 历史/界面可能写入的中文角色码 → 标准 code
ROLE_CODE_ALIASES = {
    '财务': 'finance',
    '管理员': 'admin',
    '系统管理员': 'admin',
    '超级管理员': 'admin',
    '系统超级管理员': 'admin',
    '超级管理': 'admin',
    '项目经理': 'manager',
    '普通用户': 'user',
    'superadmin': 'admin',
    'super_admin': 'admin',
    'administrator': 'admin',
}


def normalize_staff_role(role):
    """统一 session/库中的角色码，便于判断 finance 等全项目权限。"""
    if role is None:
        return ''
    raw = str(role).strip()
    if not raw:
        return ''
    if raw in ROLE_CODE_ALIASES:
        return ROLE_CODE_ALIASES[raw]
    low = raw.lower()
    if low in ROLE_CODE_ALIASES:
        return ROLE_CODE_ALIASES[low]
    if low in ROLE_DEFAULT_PERMISSIONS or low == ROLE_ADMIN:
        return low
    return low


def user_is_admin(role):
    return normalize_staff_role(role) == ROLE_ADMIN


def user_sees_all_projects(role):
    return normalize_staff_role(role) in PROJECT_ALL_ROLES


def ensure_user_access_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_project_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, project_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_project_assign_user
        ON user_project_assignments(user_id)
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            permission_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, permission_code),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            module TEXT,
            action TEXT,
            description TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_code TEXT NOT NULL,
            permission_code TEXT NOT NULL,
            PRIMARY KEY (role_code, permission_code)
        )
    """)
    # 种子权限定义（幂等）
    for code, name, module in PERMISSION_DEFS:
        db.execute(
            """INSERT OR IGNORE INTO permissions (code, name, module, action, description)
               VALUES (?, ?, ?, ?, ?)""",
            (code, name, module, code.split('.')[-1], name),
        )
    for role, codes in ROLE_DEFAULT_PERMISSIONS.items():
        for code in codes:
            db.execute(
                'INSERT OR IGNORE INTO role_permissions (role_code, permission_code) VALUES (?, ?)',
                (role, code),
            )
    # 清理 role_permissions 中已废弃的历史码（如 transaction_view），避免误导
    db.execute(
        'DELETE FROM role_permissions WHERE permission_code NOT IN '
        f'({",".join("?" * len(ALL_PERMISSION_CODES))})',
        tuple(ALL_PERMISSION_CODES),
    )
    db.commit()


def permission_groups():
    groups = {}
    for code, name, grp in PERMISSION_DEFS:
        groups.setdefault(grp, []).append({'code': code, 'name': name})
    return groups


def get_stored_user_permissions(db, user_id):
    ensure_user_access_schema(db)
    rows = db.execute(
        'SELECT permission_code FROM user_permissions WHERE user_id=? ORDER BY permission_code',
        (user_id,),
    ).fetchall()
    return [r['permission_code'] for r in rows]


def get_role_permissions(db, role):
    """角色默认功能权限（以代码为准，不读库里的历史 permission 码）。"""
    role = normalize_staff_role(role)
    if role in ROLE_DEFAULT_PERMISSIONS:
        return ROLE_DEFAULT_PERMISSIONS[role]
    ensure_user_access_schema(db)
    rows = db.execute(
        'SELECT permission_code FROM role_permissions WHERE role_code=?',
        (role,),
    ).fetchall()
    codes = frozenset(
        r['permission_code'] for r in rows if r['permission_code'] in ALL_PERMISSION_CODES
    )
    return codes if codes else frozenset()


def get_effective_permissions(db, user_id, role):
    role = normalize_staff_role(role)
    if role == ROLE_ADMIN:
        return ALL_PERMISSION_CODES
    if role == 'finance':
        return ROLE_DEFAULT_PERMISSIONS['finance']
    stored = get_stored_user_permissions(db, user_id)
    if stored:
        custom = frozenset(c for c in stored if c in ALL_PERMISSION_CODES)
        if custom:
            return custom
    return get_role_permissions(db, role)


def has_permission(db, user_id, role, code):
    if user_is_admin(role):
        return True
    return code in get_effective_permissions(db, user_id, role)


def set_user_permissions(db, user_id, permission_codes):
    ensure_user_access_schema(db)
    db.execute('DELETE FROM user_permissions WHERE user_id=?', (user_id,))
    for code in permission_codes:
        if code in ALL_PERMISSION_CODES:
            db.execute(
                'INSERT INTO user_permissions (user_id, permission_code) VALUES (?, ?)',
                (user_id, code),
            )


def get_assigned_project_ids(db, user_id, role):
    """None=全部项目；list=仅授权项目（可为空）。"""
    role = normalize_staff_role(role)
    if role in PROJECT_ALL_ROLES:
        return None
    if role in COLLAB_ONLY_ROLES:
        return []
    ensure_user_access_schema(db)
    rows = db.execute(
        'SELECT project_id FROM user_project_assignments WHERE user_id=? ORDER BY project_id',
        (user_id,),
    ).fetchall()
    return [r['project_id'] for r in rows]


def set_user_project_assignments(db, user_id, project_ids, created_by=None):
    ensure_user_access_schema(db)
    db.execute('DELETE FROM user_project_assignments WHERE user_id=?', (user_id,))
    for pid in project_ids:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        exists = db.execute('SELECT id FROM projects WHERE id=?', (pid,)).fetchone()
        if exists:
            db.execute(
                """INSERT INTO user_project_assignments (user_id, project_id, created_by)
                   VALUES (?, ?, ?)""",
                (user_id, pid, created_by),
            )


def can_access_project(db, user_id, role, project_id):
    """单据/项目是否在当前用户数据范围内。"""
    role = normalize_staff_role(role)
    if role in PROJECT_ALL_ROLES:
        return True
    if project_id is None or project_id == '':
        # 未绑定项目的单据：仅全项目角色可访问（见上）；其余角色不可通过详情绕过列表
        return False
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return False
    ids = get_assigned_project_ids(db, user_id, role)
    if ids is None:
        return True
    return pid in ids


def assert_project_access(db, user_id, role, project_id, *, redirect_endpoint='project_list'):
    if can_access_project(db, user_id, role, project_id):
        return None
    flash('无权访问该项目（未授权）', 'danger')
    return redirect(url_for(redirect_endpoint))


def list_projects_for_user(db, user_id, role, order='ORDER BY created_at DESC'):
    ids = get_assigned_project_ids(db, user_id, role)
    if ids is None:
        return db.execute(f'SELECT * FROM projects {order}').fetchall()
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    return db.execute(
        f'SELECT * FROM projects WHERE id IN ({ph}) {order}',
        ids,
    ).fetchall()


def project_filter_clause(db, user_id, role, alias='p'):
    """返回 (sql_fragment, params) 用于 AND 条件；无限制时 ('', [])。"""
    ids = get_assigned_project_ids(db, user_id, role)
    if ids is None:
        return '', []
    if not ids:
        return f' AND {alias}.id IN (-1) ', []
    ph = ','.join('?' * len(ids))
    return f' AND {alias}.id IN ({ph}) ', list(ids)


def project_id_scope_clause(db, user_id, role, column_expr):
    """按授权项目过滤任意 project_id 列，如 po.project_id。返回 (sql_fragment, params)。"""
    ids = get_assigned_project_ids(db, user_id, role)
    if ids is None:
        return '', []
    if not ids:
        return ' AND 1=0 ', []
    ph = ','.join('?' * len(ids))
    return f' AND {column_expr} IN ({ph}) ', list(ids)


def append_project_scope_to_parts(db, user_id, role, table_alias, parts, params):
    """向 SQL parts 列表追加项目范围（用于 invoice 等动态 WHERE）。"""
    ids = get_assigned_project_ids(db, user_id, role)
    if ids is None:
        return
    if not ids:
        parts.append('1=0')
        return
    ph = ','.join('?' * len(ids))
    parts.append(f'{table_alias}.project_id IN ({ph})')
    params.extend(ids)


def delete_user_safely(db, uid):
    """删除用户并清理/解除外键引用。"""
    ensure_user_access_schema(db)
    from client_collab_scope import ensure_collab_scope_schema
    ensure_collab_scope_schema(db)

    def _nullify(table, col):
        try:
            cols = {r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
            if col in cols:
                db.execute(f'UPDATE {table} SET {col}=NULL WHERE {col}=?', (uid,))
        except Exception:
            pass

    _nullify('projects', 'user_id')
    _nullify('client_accounts', 'approved_by')
    _nullify('client_recharges', 'confirmed_by')
    _nullify('participants', 'user_id')
    _nullify('purchase_orders', 'created_by')
    _nullify('sales_orders', 'created_by')
    _nullify('invoices', 'created_by')
    _nullify('users', 'created_by')
    _nullify('users', 'approved_by')

    for table in (
        'client_collab_assignments',
        'user_project_assignments',
        'user_permissions',
        'user_category_permissions',
        'user_report_favorites',
    ):
        try:
            db.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))
        except Exception:
            pass

    try:
        db.execute('DELETE FROM user_report_hub_prefs WHERE user_id=?', (uid,))
    except Exception:
        pass

    db.execute('DELETE FROM logs WHERE user_id=?', (uid,))
    db.execute('DELETE FROM users WHERE id=?', (uid,))
