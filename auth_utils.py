# -*- coding: utf-8 -*-
"""内部账号模块访问控制（客户协同隔离）"""
from functools import wraps
from flask import session, redirect, url_for, flash, request

ROLE_ADMIN = 'admin'
ROLE_CLIENT_COLLAB = 'client_collab'
ROLE_CLIENT_COLLAB_ADMIN = 'client_collab_admin'
MODULE_CLIENT_PORTAL = 'client_portal'

# 客户协同模块内部角色（仅可访问客户协同模块，不可进入其它业务模块）
COLLAB_ONLY_ROLES = frozenset({ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN})

ROLE_LABELS = {
    'admin': '系统管理员',
    'client_collab_admin': '客户协同管理员',
    'client_collab': '客户协同专员',
    'finance': '财务',
    'manager': '项目经理',
    'user': '普通用户',
}

# 客户协同管理员额外可访问的「协同专员管理」端点
COLLAB_ADMIN_STAFF_ENDPOINTS = frozenset({
    'admin_collab_staff',
    'admin_collab_staff_create',
    'admin_collab_staff_assign',
    'admin_collab_staff_reset',
    'admin_collab_staff_toggle',
    'admin_collab_staff_delete',
})

# 需协同管理员或系统管理员才可操作（账户授权、充值审核、同步等）
COLLAB_AUTHORIZE_ENDPOINTS = frozenset({
    'admin_client_accounts',
    'admin_client_accounts_create',
    'admin_client_account_approve',
    'admin_client_account_reject',
    'admin_client_account_enable',
    'admin_client_account_disable',
    'admin_client_account_bind',
    'admin_client_account_reset_password',
    'admin_client_account_update',
    'admin_client_recharge_confirm',
    'admin_client_recharge_reject',
    'admin_client_recharge_unconfirm',
    'admin_client_recharge_batch_confirm',
    'admin_client_recharge_batch_reject',
    'admin_client_recharge_batch_unconfirm',
    'admin_client_deductions_sync',
}) | COLLAB_ADMIN_STAFF_ENDPOINTS

# 协同专员：仅数据录入 / 查询 / 修改（不含授权与系统设置）
COLLAB_DATA_ENDPOINTS = frozenset({
    'admin_client_dashboard',
    'admin_client_workspace',
    'admin_client_company_recharge',
    'admin_client_company_outbound',
    'admin_client_company_other_deduct',
    'admin_client_company_excel_import',
    'admin_client_company_excel_preview',
    'admin_client_company_excel_import_confirm',
    'admin_client_company_ocr_upload',
    'admin_client_company_ocr_apply',
    'admin_client_recharges',
    'admin_client_recharge_update',
    'admin_client_recharge_delete',
    'admin_client_deduction_update',
    'admin_client_deduction_delete',
    'admin_client_reports',
    'admin_client_reports_view',
    'login',
    'logout',
    'static',
})

# 客户协同模块全部内部路由（管理员 / 协同管理员）
CLIENT_PORTAL_ENDPOINTS = COLLAB_DATA_ENDPOINTS | COLLAB_AUTHORIZE_ENDPOINTS

PUBLIC_ENDPOINTS = frozenset({
    'login', 'logout', 'static',
    'portal_login', 'portal_register', 'portal_logout',
    'uploaded_file', 'serve_ocr_image', 'serve_upload_file',
})


def can_collab_authorize(role):
    """是否可进行账户授权、充值审核等管理操作。"""
    return role in (ROLE_ADMIN, ROLE_CLIENT_COLLAB_ADMIN)


def is_portal_client_session():
    """客户门户登录（仅 client_id，无内部 user_id）。"""
    return 'client_id' in session and 'user_id' not in session


def is_client_portal_admin_endpoint(endpoint):
    if not endpoint:
        return False
    return endpoint.startswith('admin_client')


def can_access_endpoint(role, endpoint):
    if not endpoint or endpoint in PUBLIC_ENDPOINTS:
        return True
    if endpoint.startswith('static'):
        return True

    if role == ROLE_CLIENT_COLLAB_ADMIN:
        # 协同管理员：客户协同模块全部 + 协同专员管理 + 客户资金报表
        if endpoint in CLIENT_PORTAL_ENDPOINTS:
            return True
        if endpoint in COLLAB_ADMIN_STAFF_ENDPOINTS:
            return True
        if endpoint and endpoint.startswith('reports.'):
            return True
        return False

    if role == ROLE_CLIENT_COLLAB:
        if endpoint in COLLAB_AUTHORIZE_ENDPOINTS:
            return False
        if endpoint in COLLAB_DATA_ENDPOINTS:
            return True
        if endpoint and endpoint.startswith('reports.'):
            return True
        return False

    if is_client_portal_admin_endpoint(endpoint):
        return role in (ROLE_ADMIN, ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN)

    return True


def login_redirect_for_role(role):
    if role in COLLAB_ONLY_ROLES:
        return url_for('admin_client_dashboard')
    return url_for('dashboard')


def module_required(module_name):
    """仅 admin 与 client_collab 可访问客户协同管理端点。"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            role = session.get('role')
            if module_name == MODULE_CLIENT_PORTAL:
                if role not in (ROLE_ADMIN, ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN):
                    flash('无权访问客户协同管理', 'danger')
                    return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_or_collab_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') not in (ROLE_ADMIN, ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN):
            flash('权限不足', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapped


def collab_admin_required(f):
    """仅系统管理员或客户协同管理员可访问（用于协同专员管理）。"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        role = session.get('role')
        if role not in (ROLE_ADMIN, ROLE_CLIENT_COLLAB_ADMIN):
            flash('权限不足，仅协同管理员可操作', 'danger')
            return redirect(login_redirect_for_role(role))
        return f(*args, **kwargs)
    return wrapped


def collab_authorize_required(f):
    """仅系统管理员或客户协同管理员（账户授权、充值审核等）。"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        role = session.get('role')
        if not can_collab_authorize(role):
            flash('权限不足，您仅可录入、查询和修改业务数据', 'danger')
            return redirect(login_redirect_for_role(role))
        return f(*args, **kwargs)
    return wrapped


def staff_layout_template():
    """内部员工页面布局：协同角色使用独立导航，与 ERP 完全分离。"""
    from flask import session
    if session.get('role') in COLLAB_ONLY_ROLES:
        return 'collab_base.html'
    return 'nav_base.html'


def register_auth_hooks(app):
    @app.context_processor
    def inject_auth_context():
        from flask import session
        role = session.get('role', '')
        return {
            'staff_layout': staff_layout_template() if role else 'nav_base.html',
            'role_display': ROLE_LABELS.get(role, role),
            'is_collab_staff': role in COLLAB_ONLY_ROLES,
            'is_collab_admin': role == ROLE_CLIENT_COLLAB_ADMIN,
            'is_system_admin': role == ROLE_ADMIN,
            'can_collab_authorize': can_collab_authorize(role),
        }

    @app.before_request
    def enforce_portal_client_isolation():
        """客户门户账号只能访问 /portal/*，不能进入内部管理端。"""
        if not is_portal_client_session():
            return None
        endpoint = request.endpoint
        if not endpoint or endpoint in PUBLIC_ENDPOINTS:
            return None
        if endpoint.startswith('static'):
            return None
        if endpoint.startswith('portal_'):
            return None
        flash('客户账户无权访问该功能', 'danger')
        return redirect(url_for('portal_index'))

    @app.before_request
    def enforce_internal_module_access():
        if 'user_id' not in session:
            return None
        endpoint = request.endpoint
        role = session.get('role')
        if not can_access_endpoint(role, endpoint):
            flash('无权访问该功能', 'danger')
            return redirect(login_redirect_for_role(role))
        return None
