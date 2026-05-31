# -*- coding: utf-8 -*-
"""报表中心 Blueprint"""
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, send_file, jsonify,
)

from auth_utils import ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN
from client_collab_scope import COLLAB_REPORT_SLUGS, report_allowed_for_role
from report_registry import (
    FEATURED_SLUG,
    MODULE_UI,
    REPORT_CARD_ICONS,
    get_report as get_report_meta,
    reports_by_module,
    REPORT_MODULES,
    REPORT_VIEW_ROLES,
    REPORT_EXPORT_ROLES,
)
from report_service import parse_filters, run_report, load_projects, chart_data_json
from report_export import export_to_xlsx, export_filename
from report_hub_prefs import (
    get_hub_prefs,
    toggle_favorite,
    set_dark_mode,
    get_favorite_slugs,
)
from report_hub_preview import preview_metrics, hub_default_filters

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


_get_db_fn = None


def _get_db():
    if _get_db_fn:
        return _get_db_fn()
    from flask import g
    return g.db


COLLAB_REPORT_ROLES = frozenset({ROLE_CLIENT_COLLAB, ROLE_CLIENT_COLLAB_ADMIN})


def report_view_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        role = session.get('role', '')
        slug = (request.view_args or {}).get('slug')
        if role in COLLAB_REPORT_ROLES:
            if request.endpoint == 'reports.export':
                flash('无权导出报表', 'danger')
                return redirect(url_for('reports.hub'))
            if request.endpoint == 'reports.view' and slug not in COLLAB_REPORT_SLUGS:
                flash('无权访问该报表', 'danger')
                return redirect(url_for('reports.hub'))
            return f(*args, **kwargs)
        elif role not in REPORT_VIEW_ROLES:
            flash('无权访问报表中心', 'danger')
            from auth_utils import login_redirect_for_role
            return redirect(login_redirect_for_role(role))
        return f(*args, **kwargs)
    return wrapped


def report_export_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        role = session.get('role', '')
        if role not in REPORT_EXPORT_ROLES:
            flash('无权导出报表', 'danger')
            return redirect(request.referrer or url_for('reports.hub'))
        return f(*args, **kwargs)
    return wrapped


@reports_bp.route('')
@report_view_required
def hub():
    # 兼容旧链接 /reports?project_id=
    if request.args.get('project_id') and not request.args.get('slug'):
        return redirect(url_for(
            'reports.view',
            slug='fee-profit',
            project_id=request.args.get('project_id'),
            date_from=request.args.get('date_from', ''),
            date_to=request.args.get('date_to', ''),
        ))
    role = session.get('role', '')
    grouped = reports_by_module(enabled_only=True, role=role)
    modules = REPORT_MODULES
    if role in COLLAB_REPORT_ROLES:
        modules = [('client', '客户协同')]
    report_cards = []
    for mod_code, mod_label in modules:
        ui = MODULE_UI.get(mod_code, {})
        for r in grouped.get(mod_code, []):
            report_cards.append({
                **r,
                'module': mod_code,
                'module_label': mod_label,
                'icon': REPORT_CARD_ICONS.get(r['slug'], ui.get('icon', 'bi-bar-chart')),
                'accent': ui.get('accent', '#4361ee'),
                'gradient': ui.get('gradient', ''),
                'module_tagline': ui.get('tagline', ''),
                'featured': r['slug'] == FEATURED_SLUG and mod_code == 'global',
            })
    user_id = session.get('user_id')
    db = _get_db()
    fav_slugs = get_favorite_slugs(db, user_id) if user_id else []
    hub_prefs = get_hub_prefs(db, user_id) if user_id else {'dark_mode': False}
    fav_set = set(fav_slugs)
    for card in report_cards:
        card['favorited'] = card['slug'] in fav_set
    default_filters = hub_default_filters(user_id, role) if user_id else {}

    return render_template(
        'reports/hub.html',
        grouped=grouped,
        modules=modules,
        module_ui=MODULE_UI,
        report_cards=report_cards,
        total_reports=len(report_cards),
        featured_slug=FEATURED_SLUG,
        is_collab_report_hub=role in COLLAB_REPORT_ROLES,
        favorite_slugs=fav_slugs,
        hub_dark_mode=hub_prefs.get('dark_mode', False),
        preview_period=f'{default_filters.get("date_from", "")} ~ {default_filters.get("date_to", "")}',
    )


@reports_bp.route('/api/prefs', methods=['GET'])
@report_view_required
def api_prefs():
    user_id = session.get('user_id')
    db = _get_db()
    prefs = get_hub_prefs(db, user_id)
    return jsonify({'ok': True, **prefs})


@reports_bp.route('/api/prefs', methods=['PUT', 'POST'])
@report_view_required
def api_prefs_update():
    user_id = session.get('user_id')
    body = request.get_json(silent=True) or {}
    if 'dark_mode' in body:
        db = _get_db()
        set_dark_mode(db, user_id, bool(body['dark_mode']))
    prefs = get_hub_prefs(_get_db(), user_id)
    return jsonify({'ok': True, **prefs})


@reports_bp.route('/api/favorites/<slug>', methods=['POST'])
@report_view_required
def api_toggle_favorite(slug):
    meta = get_report_meta(slug)
    if not meta or not meta.get('enabled', True):
        return jsonify({'ok': False, 'message': '报表不存在'}), 404
    role = session.get('role', '')
    if not report_allowed_for_role(slug, role):
        return jsonify({'ok': False, 'message': '无权收藏'}), 403
    user_id = session.get('user_id')
    db = _get_db()
    favorited, favs = toggle_favorite(db, user_id, slug)
    return jsonify({'ok': True, 'favorited': favorited, 'favorites': favs})


@reports_bp.route('/api/preview/<slug>')
@report_view_required
def api_preview(slug):
    role = session.get('role', '')
    if not report_allowed_for_role(slug, role):
        return jsonify({'ok': False, 'message': '无权访问'}), 403
    user_id = session.get('user_id')
    db = _get_db()
    payload = preview_metrics(db, slug, user_id, role)
    if not payload:
        return jsonify({'ok': False, 'message': '暂无预览数据'}), 404
    return jsonify({'ok': True, **payload})


@reports_bp.route('/<slug>')
@report_view_required
def view(slug):
    meta = get_report_meta(slug)
    if not meta or not meta.get('enabled', True):
        flash('报表不存在或尚未开放', 'warning')
        return redirect(url_for('reports.hub'))
    role = session.get('role', '')
    if not report_allowed_for_role(slug, role):
        flash('无权访问该报表', 'danger')
        return redirect(url_for('reports.hub'))

    db = _get_db()
    filters = parse_filters(request)
    filters['_scope_user_id'] = session.get('user_id')
    filters['_scope_role'] = role
    data = run_report(db, slug, filters)
    if data is None:
        flash('报表数据加载失败', 'danger')
        return redirect(url_for('reports.hub'))

    projects = load_projects(db)
    template = meta.get('template') or 'view.html'
    chart_json = chart_data_json(data.get('chart_data') or {})

    ctx = {
        'slug': slug,
        'meta': meta,
        'filters': filters,
        'projects': projects,
        'data': data,
        'chart_data': chart_json,
        'filter_fields': meta.get('filters', []),
    }
    return render_template(f'reports/{template}', **ctx)


@reports_bp.route('/<slug>/export')
@report_view_required
@report_export_required
def export(slug):
    meta = get_report_meta(slug)
    if not meta or not meta.get('enabled', True):
        flash('报表不存在', 'warning')
        return redirect(url_for('reports.hub'))

    role = session.get('role', '')
    if not report_allowed_for_role(slug, role):
        flash('无权导出该报表', 'danger')
        return redirect(url_for('reports.hub'))

    db = _get_db()
    filters = parse_filters(request)
    filters['_scope_user_id'] = session.get('user_id')
    filters['_scope_role'] = role
    data = run_report(db, slug, filters)
    if not data:
        flash('无数据可导出', 'warning')
        return redirect(url_for('reports.view', slug=slug, **request.args))

    rows = data.get('export_rows') or data.get('table_rows') or []
    columns = data.get('table_columns')
    buf = export_to_xlsx(meta['title'], rows, columns)
    fname = export_filename(meta['title'], filters['date_from'], filters['date_to'])
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=fname,
    )


def register_reports_blueprint(app, get_db_fn):
    """注册报表 Blueprint。"""
    global _get_db_fn
    _get_db_fn = get_db_fn
    app.register_blueprint(reports_bp)
