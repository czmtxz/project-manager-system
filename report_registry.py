# -*- coding: utf-8 -*-
"""报表中心元数据注册表"""

REPORT_MODULES = [
    ('global', '综合经营'),
    ('fee', '项目费用'),
    ('sales', '销售'),
    ('purchase', '采购'),
    ('contract', '合同发票'),
    ('investment', '投资管理'),
    ('reconciliation', '对账'),
    ('client', '客户协同'),
]

# 模块展示（报表中心 UI）
MODULE_UI = {
    'global': {
        'icon': 'bi-stars',
        'accent': '#6366f1',
        'gradient': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 55%, #a78bfa 100%)',
        'tagline': '一眼掌握经营脉搏',
    },
    'fee': {
        'icon': 'bi-pie-chart',
        'accent': '#10b981',
        'gradient': 'linear-gradient(135deg, #059669 0%, #34d399 100%)',
        'tagline': '账目清晰，利润可见',
    },
    'sales': {
        'icon': 'bi-cart-check',
        'accent': '#f59e0b',
        'gradient': 'linear-gradient(135deg, #d97706 0%, #fbbf24 100%)',
        'tagline': '出库回款，尽在掌握',
    },
    'purchase': {
        'icon': 'bi-truck',
        'accent': '#0ea5e9',
        'gradient': 'linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)',
        'tagline': '采购运费，成本透明',
    },
    'contract': {
        'icon': 'bi-file-earmark-text',
        'accent': '#64748b',
        'gradient': 'linear-gradient(135deg, #475569 0%, #94a3b8 100%)',
        'tagline': '合同发票，业财一体',
    },
    'investment': {
        'icon': 'bi-piggy-bank',
        'accent': '#ec4899',
        'gradient': 'linear-gradient(135deg, #db2777 0%, #f472b6 100%)',
        'tagline': '出资回报，心中有数',
    },
    'reconciliation': {
        'icon': 'bi-calculator',
        'accent': '#14b8a6',
        'gradient': 'linear-gradient(135deg, #0d9488 0%, #2dd4bf 100%)',
        'tagline': '对账差异，及时预警',
    },
    'client': {
        'icon': 'bi-people',
        'accent': '#8b5cf6',
        'gradient': 'linear-gradient(135deg, #7c3aed 0%, #c4b5fd 100%)',
        'tagline': '客户资金，协同可视',
    },
}

REPORT_CARD_ICONS = {
    'executive-overview': 'bi-rocket-takeoff',
    'project-profit': 'bi-trophy',
    'cash-flow': 'bi-cash-stack',
    'business-alerts': 'bi-exclamation-triangle',
    'fee-profit': 'bi-graph-up-arrow',
    'fee-category': 'bi-diagram-3',
    'sales-outbound': 'bi-box-seam',
    'sales-collection': 'bi-wallet2',
    'purchase-spend': 'bi-bag-check',
    'transport-freight': 'bi-truck-flatbed',
    'contract-funnel': 'bi-funnel',
    'invoice-summary': 'bi-receipt',
    'investment-dividend': 'bi-piggy-bank',
    'reconciliation-summary': 'bi-shuffle',
    'client-collab-funds': 'bi-building-check',
}

FEATURED_SLUG = 'executive-overview'

# slug -> meta
REPORTS = {
    'executive-overview': {
        'title': '经营驾驶舱',
        'module': 'global',
        'description': '全公司经营指标、月度趋势与项目毛利排行',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 1,
        'enabled': True,
    },
    'project-profit': {
        'title': '项目盈利对比',
        'module': 'global',
        'description': '各项目预算、费用收支、毛利与预算使用率',
        'filters': ['date_from', 'date_to'],
        'phase': 1,
        'enabled': True,
    },
    'cash-flow': {
        'title': '资金收支趋势',
        'module': 'global',
        'description': '费用收支与销售回款按月汇总',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 1,
        'enabled': True,
    },
    'business-alerts': {
        'title': '经营预警一览',
        'module': 'global',
        'description': '预算超支、未回款、待对账、客户低余额预警',
        'filters': [],
        'phase': 1,
        'enabled': True,
    },
    'fee-profit': {
        'title': '费用盈亏分析',
        'module': 'fee',
        'description': '项目费用收入、支出、利润与分类分布',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 1,
        'enabled': True,
        'template': 'fee_profit.html',
    },
    'fee-category': {
        'title': '费用分类结构',
        'module': 'fee',
        'description': '三级费用科目结构与支出 Top 科目',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 1,
        'enabled': True,
        'template': 'fee_category.html',
    },
    'sales-outbound': {
        'title': '销售出库分析',
        'module': 'sales',
        'description': '销售订单金额、吨数与客户/月度分布',
        'filters': ['date_from', 'date_to', 'project_id', 'customer_name'],
        'phase': 1,
        'enabled': True,
    },
    'sales-collection': {
        'title': '销售回款分析',
        'module': 'sales',
        'description': '应收、已回款、回款率与客户维度汇总',
        'filters': ['date_from', 'date_to', 'project_id', 'customer_name'],
        'phase': 1,
        'enabled': True,
    },
    'purchase-spend': {
        'title': '采购支出分析',
        'module': 'purchase',
        'description': '采购单数量、金额与供应商/月度分布',
        'filters': ['date_from', 'date_to', 'project_id', 'supplier'],
        'phase': 1,
        'enabled': True,
    },
    'transport-freight': {
        'title': '运费成本分析',
        'module': 'purchase',
        'description': '运输车次、运费、吨数与吨运费均价',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 1,
        'enabled': True,
    },
  # ---------- 二期 ----------
    'contract-funnel': {
        'title': '合同执行漏斗',
        'module': 'contract',
        'description': '合同金额、已开票、已回款/付款执行进度',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 2,
        'enabled': True,
    },
    'invoice-summary': {
        'title': '进销项发票汇总',
        'module': 'contract',
        'description': '进项/销项发票金额、税额与月度分布',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 2,
        'enabled': True,
    },
    'investment-dividend': {
        'title': '出资与分红',
        'module': 'investment',
        'description': '参与人出资、分红及回报概览',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 2,
        'enabled': True,
        'template': 'investment_dividend.html',
    },
    'reconciliation-summary': {
        'title': '对账差异汇总',
        'module': 'reconciliation',
        'description': '采购到货与运输吨差、运费与发票差异',
        'filters': ['date_from', 'date_to', 'project_id'],
        'phase': 2,
        'enabled': True,
    },
    'client-collab-funds': {
        'title': '客户资金全景',
        'module': 'client',
        'description': '协同客户充值、扣减、余额与期间趋势（按负责客户隔离）',
        'filters': ['date_from', 'date_to'],
        'phase': 2,
        'enabled': True,
        'view_roles': ['admin', 'finance', 'client_collab', 'client_collab_admin'],
    },
}


def report_visible_for_role(meta, role):
    """按角色过滤可见报表（客户协同类报表对项目经理等隐藏）。"""
    allowed = meta.get('view_roles')
    if not allowed:
        return True
    return role in allowed

REPORT_VIEW_ROLES = frozenset({'admin', 'finance', 'manager'})
REPORT_EXPORT_ROLES = frozenset({'admin', 'finance'})


def get_report(slug):
    return REPORTS.get(slug)


def list_reports(phase=None, enabled_only=True):
    out = []
    for slug, meta in REPORTS.items():
        if enabled_only and not meta.get('enabled', True):
            continue
        if phase is not None and meta.get('phase') != phase:
            continue
        out.append({'slug': slug, **meta})
    return out


def reports_by_module(enabled_only=True, role=None):
    grouped = {m[0]: [] for m in REPORT_MODULES}
    for slug, meta in REPORTS.items():
        if enabled_only and not meta.get('enabled', True):
            continue
        if role is not None and not report_visible_for_role(meta, role):
            continue
        mod = meta.get('module', 'global')
        if mod not in grouped:
            grouped[mod] = []
        grouped[mod].append({'slug': slug, **meta})
    return grouped
