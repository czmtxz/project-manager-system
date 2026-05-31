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

# 客户协同专员可访问的内部路由
CLIENT_PORTAL_ENDPOINTS = frozenset({
    'admin_client_dashboard',
    'admin_client_workspace',
    'admin_client_company_recharge',
    'admin_client_company_outbound',
    'admin_client_company_excel_import',
    'admin_client_company_excel_preview',
    'admin_client_company_excel_import_confirm',
    'admin_client_company_ocr_upload',
    'admin_client_company_ocr_apply',
    'admin_client_accounts',
    'admin_client_account_approve',
    'admin_client_account_reject',
    'admin_client_account_enable',
    'admin_client_account_disable',
    'admin_client_accounts_create',
    'admin_client_account_bind',
    'admin_client_account_reset_password',
    'admin_client_recharges',
    'admin_client_recharge_confirm',
    'admin_client_recharge_reject',
    'admin_client_recharge_unconfirm',
    'admin_client_recharge_batch_confirm',
    'admin_client_recharge_batch_reject',
    'admin_client_recharge_batch_unconfirm',
    'admin_client_deductions_sync',
    'admin_client_recharge_update',
    'admin_client_recharge_delete',
    'admin_client_deduction_update',
    'admin_client_deduction_delete',
    'login',
    'logout',
    'static',
})

PUBLIC_ENDPOINTS = frozenset({
    'login', 'logout', 'static',
    'portal_login', 'portal_register', 'portal_logout',
    'uploaded_file', 'serve_ocr_image', 'serve_upload_file',
})


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
        if endpoint in CLIENT_PORTAL_ENDPOINTS:
            return True
        # 报表中心：仅允许客户资金报表（slug 在 reports_routes 内二次校验）
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
        }

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
