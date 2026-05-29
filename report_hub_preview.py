# -*- coding: utf-8 -*-
"""报表中心卡片预览指标（本年默认区间）"""
from datetime import date

from client_collab_scope import report_allowed_for_role
from report_registry import get_report
from report_service import run_report


def hub_default_filters(user_id, role):
    today = date.today()
    year_start = date(today.year, 1, 1)
    return {
        'date_from': year_start.isoformat(),
        'date_to': today.isoformat(),
        'project_id': '',
        'customer_name': '',
        'supplier': '',
        '_scope_user_id': user_id,
        '_scope_role': role,
    }


def preview_metrics(db, slug, user_id, role):
    if not report_allowed_for_role(slug, role):
        return None
    meta = get_report(slug)
    if not meta or not meta.get('enabled', True):
        return None
    filters = hub_default_filters(user_id, role)
    try:
        data = run_report(db, slug, filters)
    except Exception:
        return None
    if not data:
        return None
    kpis = data.get('kpis') or []
    metrics = [
        {'label': k.get('label', ''), 'value': str(k.get('value', '—'))}
        for k in kpis[:4]
    ]
    return {
        'slug': slug,
        'title': meta.get('title', slug),
        'period': f'{filters["date_from"]} ~ {filters["date_to"]}',
        'metrics': metrics,
        'footnote': (data.get('footnote') or '')[:120],
    }
