# -*- coding: utf-8 -*-
"""报表数据查询与聚合"""
import json
from datetime import date, datetime, timedelta

from route_extensions import build_category_tree


_purchase_date_col_cache = {}
_payment_customer_col_cache = {}


def purchase_date_column(db):
    key = id(db)
    if key not in _purchase_date_col_cache:
        cols = [r[1] for r in db.execute('PRAGMA table_info(purchase_orders)').fetchall()]
        _purchase_date_col_cache[key] = 'order_date' if 'order_date' in cols else 'purchase_date'
    return _purchase_date_col_cache[key]


def payment_customer_column(db):
    """回款表用于匹配客户的字段：customer_name 或 payer。"""
    key = id(db)
    if key not in _payment_customer_col_cache:
        cols = [r[1] for r in db.execute('PRAGMA table_info(sales_payments)').fetchall()]
        _payment_customer_col_cache[key] = 'customer_name' if 'customer_name' in cols else 'payer'
    return _payment_customer_col_cache[key]


def _parse_include_draft_report(request, default=False):
    vals = request.args.getlist('include_draft')
    if vals:
        return str(vals[-1]).lower() in ('1', 'true', 'on', 'yes')
    return default if not request.args else False


def parse_filters(request):
    today = date.today()
    year_start = date(today.year, 1, 1)
    date_from = (request.args.get('date_from') or '').strip() or year_start.isoformat()
    date_to = (request.args.get('date_to') or '').strip() or today.isoformat()
    project_id = (request.args.get('project_id') or '').strip()
    customer_name = (request.args.get('customer_name') or '').strip()
    supplier = (request.args.get('supplier') or '').strip()
    item_name = (request.args.get('item_name') or '').strip()
    specification = (request.args.get('specification') or '').strip()
    group_by = (request.args.get('group_by') or 'detail').strip() or 'detail'
    return {
        'date_from': date_from,
        'date_to': date_to,
        'project_id': project_id,
        'customer_name': customer_name,
        'supplier': supplier,
        'item_name': item_name,
        'specification': specification,
        'group_by': group_by,
        'include_draft': _parse_include_draft_report(request, default=True),
    }


def _where(parts, params):
    if not parts:
        return '', params
    return ' WHERE ' + ' AND '.join(parts), params


def _append_project_scope(filters, alias, parts, params):
    """非管理员/财务：报表仅统计已授权项目。"""
    scoped = filters.get('_scoped_project_ids')
    if scoped is None:
        return
    if not scoped:
        parts.append('1=0')
        return
    if filters.get('project_id'):
        try:
            pid = int(filters['project_id'])
            if pid not in scoped:
                parts.append('1=0')
            return
        except (TypeError, ValueError):
            pass
    ph = ','.join('?' * len(scoped))
    parts.append(f'{alias}.project_id IN ({ph})')
    params.extend(scoped)


def apply_report_project_scope(db, filters):
    user_id = filters.get('_scope_user_id')
    role = filters.get('_scope_role')
    if user_id is None or role is None:
        return
    from user_access import get_assigned_project_ids
    filters['_scoped_project_ids'] = get_assigned_project_ids(db, user_id, role)


def _trans_filters(filters, alias='t'):
    parts, params = [], []
    _append_project_scope(filters, alias, parts, params)
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('date_from'):
        parts.append(f'{alias}.trans_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{alias}.trans_date<=?')
        params.append(filters['date_to'])
    return parts, params


def _sales_order_filters(filters, alias='so'):
    parts, params = [], []
    _append_project_scope(filters, alias, parts, params)
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('customer_name'):
        parts.append(f'{alias}.customer_name LIKE ?')
        params.append(f'%{filters["customer_name"]}%')
    if filters.get('date_from'):
        parts.append(f'{alias}.order_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{alias}.order_date<=?')
        params.append(filters['date_to'])
    return parts, params


def _sales_item_order_join(db):
    cols = {r[1] for r in db.execute('PRAGMA table_info(sales_order_items)').fetchall()}
    if 'sales_order_id' in cols and 'order_id' in cols:
        return '(soi.sales_order_id = so.id OR soi.order_id = so.id)'
    if 'sales_order_id' in cols:
        return 'soi.sales_order_id = so.id'
    return 'soi.order_id = so.id'


def _sql_sales_transport_ids(so_alias='so', db=None):
    """销售出库单关联的运输记录 ID（与详情/对账逻辑一致）。"""
    parts = []
    if db is not None:
        tr_cols = {r[1] for r in db.execute('PRAGMA table_info(transport_records)').fetchall()}
        soi_link = _sales_item_order_join(db).replace('soi.', 'soi2.')
        if 'sales_order_id' in tr_cols:
            parts.append(
                f'SELECT tr0.id FROM transport_records tr0 WHERE tr0.sales_order_id = {so_alias}.id'
            )
        parts.append(
            f"""SELECT sit.transport_id FROM sales_item_transport sit
                INNER JOIN sales_order_items soi2 ON sit.sales_item_id = soi2.id
                WHERE {soi_link} AND sit.transport_id IS NOT NULL"""
        )
    else:
        parts.append(
            f'SELECT tr0.id FROM transport_records tr0 WHERE tr0.sales_order_id = {so_alias}.id'
        )
        parts.append(
            f"""SELECT sit.transport_id FROM sales_item_transport sit
                INNER JOIN sales_order_items soi ON sit.sales_item_id = soi.id
                WHERE soi.sales_order_id = {so_alias}.id"""
        )
    return ' UNION '.join(parts) if parts else 'SELECT NULL WHERE 0'


def _sql_sales_order_freight(so_alias='so', db=None):
    ids_sql = _sql_sales_transport_ids(so_alias, db)
    return f"""(SELECT COALESCE(SUM(tr.freight_amount), 0)
                FROM transport_records tr
                WHERE tr.id IN ({ids_sql}))"""


def _sql_sales_transport_qty(so_alias='so', db=None):
    ids_sql = _sql_sales_transport_ids(so_alias, db)
    return f"""(SELECT COALESCE(SUM(tr.quantity), 0)
                FROM transport_records tr
                WHERE tr.id IN ({ids_sql}))"""


def _fetch_sales_order_transports_report(db, order_id):
    """获取销售出库单下全部运输记录（直接挂出库单 + 明细关联）。"""
    tr_cols = {r[1] for r in db.execute('PRAGMA table_info(transport_records)').fetchall()}
    transports = []
    seen_ids = set()
    if 'sales_order_id' in tr_cols:
        for row in db.execute(
            """SELECT tr.* FROM transport_records tr
               WHERE tr.sales_order_id = ?
               ORDER BY tr.transport_date, tr.id""",
            (order_id,),
        ).fetchall():
            transports.append(dict(row))
            seen_ids.add(row['id'])
    item_sql, n = _sales_order_item_filter_sql_report(db, 'soi')
    item_params = _sales_order_item_filter_params_report(order_id, n)
    linked_ids = db.execute(
        f"""SELECT DISTINCT sit.transport_id
            FROM sales_item_transport sit
            JOIN sales_order_items soi ON sit.sales_item_id = soi.id
            WHERE {item_sql} AND sit.transport_id IS NOT NULL""",
        item_params,
    ).fetchall()
    extra_ids = [t['transport_id'] for t in linked_ids if t['transport_id'] not in seen_ids]
    if extra_ids:
        tid_str = ','.join(str(i) for i in extra_ids)
        for row in db.execute(
            f"""SELECT tr.* FROM transport_records tr
                WHERE tr.id IN ({tid_str})
                ORDER BY tr.transport_date, tr.id"""
        ).fetchall():
            transports.append(dict(row))
            seen_ids.add(row['id'])
    return transports


def _sales_order_item_filter_sql_report(db, alias='soi'):
    cols = {r[1] for r in db.execute('PRAGMA table_info(sales_order_items)').fetchall()}
    if 'sales_order_id' in cols and 'order_id' in cols:
        return f'({alias}.sales_order_id = ? OR {alias}.order_id = ?)', 2
    if 'sales_order_id' in cols:
        return f'{alias}.sales_order_id = ?', 1
    return f'{alias}.order_id = ?', 1


def _sales_order_item_filter_params_report(order_id, param_count):
    if param_count == 2:
        return (order_id, order_id)
    return (order_id,)


def _sales_transport_totals_map(db, order_ids):
    """出库单 ID -> 整单运费、运输数量合计。"""
    totals = {int(oid): {'freight': 0.0, 'qty': 0.0} for oid in order_ids if oid is not None}
    for oid in totals:
        seen = set()
        for t in _fetch_sales_order_transports_report(db, oid):
            tid = t.get('id')
            if tid is None or tid in seen:
                continue
            seen.add(tid)
            totals[oid]['freight'] += float(t.get('freight_amount') or 0)
            totals[oid]['qty'] += float(t.get('quantity') or 0)
    return totals


SALES_OUTBOUND_GROUP_LABELS = {
    'detail': '出库明细（逐行）',
    'customer': '按客户汇总',
    'item_name': '按品名汇总',
    'specification': '按规格型号汇总',
    'item_spec': '按品名+规格汇总',
    'date_day': '按出库日期汇总',
    'date_month': '按月份汇总',
    'project': '按项目汇总',
}


def _purchase_filters(filters, alias='po', date_col='order_date'):
    parts, params = [], []
    _append_project_scope(filters, alias, parts, params)
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('supplier'):
        parts.append(f'{alias}.supplier LIKE ?')
        params.append(f'%{filters["supplier"]}%')
    if filters.get('date_from'):
        parts.append(f'{alias}.{date_col}>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{alias}.{date_col}<=?')
        params.append(filters['date_to'])
    return parts, params


def _payment_filters(filters, alias='sp', customer_col='customer_name'):
    parts, params = [], []
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('customer_name'):
        parts.append(f'{alias}.{customer_col} LIKE ?')
        params.append(f'%{filters["customer_name"]}%')
    if filters.get('date_from'):
        parts.append(f'{alias}.payment_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{alias}.payment_date<=?')
        params.append(filters['date_to'])
    return parts, params


def _transport_filters(filters, alias='tr'):
    parts, params = [], []
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('date_from'):
        parts.append(f'{alias}.transport_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{alias}.transport_date<=?')
        params.append(filters['date_to'])
    return parts, params


def load_projects(db, user_id=None, role=None):
    if user_id is not None and role is not None:
        from user_access import list_projects_for_user
        rows = list_projects_for_user(db, user_id, role, order='ORDER BY name')
        return [{'id': r['id'], 'name': r['name']} for r in rows]
    return db.execute('SELECT id, name FROM projects ORDER BY name').fetchall()


def _contract_filters(filters, alias='c'):
    parts, params = [], []
    _append_project_scope(filters, alias, parts, params)
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('date_from'):
        parts.append(f'COALESCE({alias}.sign_date, {alias}.created_at)>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'COALESCE({alias}.sign_date, {alias}.created_at)<=?')
        params.append(filters['date_to'] + ' 23:59:59')
    return parts, params


def _invoice_filters(filters, alias='i'):
    parts, params = [], []
    _append_project_scope(filters, alias, parts, params)
    if filters.get('project_id'):
        parts.append(f'{alias}.project_id=?')
        params.append(filters['project_id'])
    if filters.get('date_from'):
        parts.append(f'COALESCE({alias}.invoice_date, {alias}.created_at)>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'COALESCE({alias}.invoice_date, {alias}.created_at)<=?')
        params.append(filters['date_to'] + ' 23:59:59')
    return parts, params


def run_report(db, slug, filters):
    runners = {
        'executive-overview': _executive_overview,
        'project-profit': _project_profit,
        'cash-flow': _cash_flow,
        'business-alerts': _business_alerts,
        'fee-profit': _fee_profit,
        'fee-category': _fee_category,
        'sales-outbound': _sales_outbound,
        'sales-outbound-detail': _sales_outbound_detail,
        'pts-summary-detail': _pts_summary_detail,
        'sales-collection': _sales_collection,
        'purchase-spend': _purchase_spend,
        'transport-freight': _transport_freight,
        'contract-funnel': _contract_funnel,
        'invoice-summary': _invoice_summary,
        'investment-dividend': _investment_dividend,
        'reconciliation-summary': _reconciliation_summary,
        'client-collab-funds': _client_collab_funds,
    }
    fn = runners.get(slug)
    if not fn:
        return None
    return fn(db, filters)


def _executive_overview(db, filters):
    tp, par = _trans_filters(filters, 't')
    w, p = _where(tp, par)
    summary = db.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as total_expense,
            COUNT(*) as fee_count
        FROM transaction_records t {w}
    """, p).fetchone()
    total_income = float(summary['total_income'] or 0)
    total_expense = float(summary['total_expense'] or 0)
    fee_profit = total_income - total_expense

    so_p, so_par = _sales_order_filters(filters, 'so')
    so_w, so_params = _where(so_p, so_par)
    sales_row = db.execute(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt,
               COALESCE(SUM(total_quantity),0) as qty
        FROM sales_orders so {so_w}
    """, so_params).fetchone()

    po_date_col = purchase_date_column(db)
    po_p, po_par = _purchase_filters(filters, 'po', po_date_col)
    po_w, po_params = _where(po_p, po_par)
    purchase_row = db.execute(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt
        FROM purchase_orders po {po_w}
    """, po_params).fetchone()

    pay_cust_col = payment_customer_column(db)
    pay_p, pay_par = _payment_filters(filters, 'sp', pay_cust_col)
    pay_w, pay_params = _where(pay_p, pay_par)
    payment_row = db.execute(f"""
        SELECT COALESCE(SUM(amount),0) as amt FROM sales_payments sp {pay_w}
    """, pay_params).fetchone()

    project_count = db.execute('SELECT COUNT(*) as c FROM projects').fetchone()['c']

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', t.trans_date) as month,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as expense
        FROM transaction_records t {w}
        GROUP BY strftime('%Y-%m', t.trans_date) ORDER BY month
    """, p).fetchall()

    t_extra = ''
    t_params = []
    if filters.get('date_from'):
        t_extra += ' AND t.trans_date>=?'
        t_params.append(filters['date_from'])
    if filters.get('date_to'):
        t_extra += ' AND t.trans_date<=?'
        t_params.append(filters['date_to'])
    top_projects = db.execute(f"""
        SELECT p.name,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as profit
        FROM projects p
        LEFT JOIN transaction_records t ON p.id = t.project_id{t_extra}
        GROUP BY p.id ORDER BY profit DESC LIMIT 10
    """, t_params).fetchall()

    months = [r['month'] for r in monthly if r['month']]
    chart_data = {
        'monthly_labels': months,
        'monthly_income': [float(r['income']) for r in monthly if r['month']],
        'monthly_expense': [float(r['expense']) for r in monthly if r['month']],
        'monthly_profit': [
            float(r['income']) - float(r['expense'])
            for r in monthly if r['month']
        ],
        'project_labels': [r['name'] for r in top_projects],
        'project_profit': [float(r['profit']) for r in top_projects],
    }

    kpis = [
        {'label': '项目数', 'value': str(project_count), 'border': 'primary'},
        {'label': '费用收入', 'value': f'{total_income:.2f}', 'border': 'success'},
        {'label': '费用支出', 'value': f'{total_expense:.2f}', 'border': 'danger'},
        {'label': '费用利润', 'value': f'{fee_profit:.2f}', 'border': 'info'},
        {'label': '销售订单额', 'value': f'{float(sales_row["amt"]):.2f}', 'border': 'success'},
        {'label': '采购总额', 'value': f'{float(purchase_row["amt"]):.2f}', 'border': 'warning'},
        {'label': '销售回款', 'value': f'{float(payment_row["amt"]):.2f}', 'border': 'primary'},
    ]

    table_rows = [
        {'指标': '费用收入', '本期': f'{total_income:.2f}'},
        {'指标': '费用支出', '本期': f'{total_expense:.2f}'},
        {'指标': '费用利润', '本期': f'{fee_profit:.2f}'},
        {'指标': '销售订单数', '本期': str(sales_row['cnt'])},
        {'指标': '销售订单额', '本期': f'{float(sales_row["amt"]):.2f}'},
        {'指标': '采购单数', '本期': str(purchase_row['cnt'])},
        {'指标': '采购总额', '本期': f'{float(purchase_row["amt"]):.2f}'},
        {'指标': '销售回款', '本期': f'{float(payment_row["amt"]):.2f}'},
    ]

    return {
        'kpis': kpis,
        'chart_data': chart_data,
        'chart_mode': 'executive',
        'table_columns': ['指标', '本期'],
        'table_rows': table_rows,
        'export_rows': table_rows,
        'footnote': '销售订单额来自 sales_orders.total_amount；回款来自 sales_payments；与合同金额口径可能不同。',
    }


def _project_profit(db, filters):
    extra = ''
    params = []
    if filters.get('date_from'):
        extra += ' AND t.trans_date>=?'
        params.append(filters['date_from'])
    if filters.get('date_to'):
        extra += ' AND t.trans_date<=?'
        params.append(filters['date_to'])

    rows = db.execute(f"""
        SELECT p.id, p.name, COALESCE(p.budget, 0) as budget,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as expense,
            COUNT(t.id) as record_count
        FROM projects p
        LEFT JOIN transaction_records t ON p.id = t.project_id{extra}
        GROUP BY p.id ORDER BY (income - expense) DESC
    """, params).fetchall()

    table_rows = []
    labels, budget_data, expense_data = [], [], []
    for r in rows:
        income = float(r['income'] or 0)
        expense = float(r['expense'] or 0)
        profit = income - expense
        budget = float(r['budget'] or 0)
        usage = (expense / budget * 100) if budget > 0 else 0
        table_rows.append({
            '项目': r['name'],
            '预算': f'{budget:.2f}',
            '费用收入': f'{income:.2f}',
            '费用支出': f'{expense:.2f}',
            '毛利': f'{profit:.2f}',
            '预算使用率%': f'{usage:.1f}',
            '笔数': r['record_count'],
            '_project_id': r['id'],
        })
        labels.append(r['name'][:12])
        budget_data.append(budget)
        expense_data.append(expense)

    return {
        'kpis': [
            {'label': '项目数', 'value': str(len(table_rows)), 'border': 'primary'},
            {'label': '费用毛利合计', 'value': f'{sum(float(x["毛利"]) for x in table_rows):.2f}', 'border': 'success'},
        ],
        'chart_data': {
            'project_labels': labels[:15],
            'budget_data': budget_data[:15],
            'expense_data': expense_data[:15],
        },
        'chart_mode': 'project_profit',
        'table_columns': ['项目', '预算', '费用收入', '费用支出', '毛利', '预算使用率%', '笔数'],
        'table_rows': table_rows,
        'export_rows': [{k: v for k, v in row.items() if not k.startswith('_')} for row in table_rows],
        'link_column': '项目',
        'link_param': '_project_id',
        'link_query': {'slug': 'fee-profit'},
    }


def _cash_flow(db, filters):
    tp, par = _trans_filters(filters, 't')
    w, p = _where(tp, par)
    pay_cust_col = payment_customer_column(db)
    monthly_fee = db.execute(f"""
        SELECT strftime('%Y-%m', t.trans_date) as month,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as expense
        FROM transaction_records t {w}
        GROUP BY month ORDER BY month
    """, p).fetchall()

    pay_p, pay_par = _payment_filters(filters, 'sp', pay_cust_col)
    pay_w, pay_params = _where(pay_p, pay_par)
    monthly_pay = db.execute(f"""
        SELECT strftime('%Y-%m', sp.payment_date) as month,
            COALESCE(SUM(sp.amount), 0) as payments
        FROM sales_payments sp {pay_w}
        GROUP BY month ORDER BY month
    """, pay_params).fetchall()

    months = sorted(set(
        [r['month'] for r in monthly_fee if r['month']] +
        [r['month'] for r in monthly_pay if r['month']]
    ))
    fee_map = {r['month']: r for r in monthly_fee}
    pay_map = {r['month']: float(r['payments'] or 0) for r in monthly_pay}

    table_rows = []
    cum_income = cum_expense = cum_pay = 0
    for m in months:
        fr = fee_map.get(m)
        inc = float(fr['income'] if fr else 0)
        exp = float(fr['expense'] if fr else 0)
        pay = pay_map.get(m, 0)
        cum_income += inc
        cum_expense += exp
        cum_pay += pay
        table_rows.append({
            '月份': m,
            '费用收入': f'{inc:.2f}',
            '费用支出': f'{exp:.2f}',
            '销售回款': f'{pay:.2f}',
            '累计收入': f'{cum_income:.2f}',
            '累计支出': f'{cum_expense:.2f}',
            '累计回款': f'{cum_pay:.2f}',
        })

    return {
        'kpis': [
            {'label': '区间费用收入', 'value': f'{sum(float(r["费用收入"]) for r in table_rows):.2f}', 'border': 'success'},
            {'label': '区间费用支出', 'value': f'{sum(float(r["费用支出"]) for r in table_rows):.2f}', 'border': 'danger'},
            {'label': '区间销售回款', 'value': f'{sum(float(r["销售回款"]) for r in table_rows):.2f}', 'border': 'primary'},
        ],
        'chart_data': {
            'monthly_labels': months,
            'monthly_income': [float(fee_map[m]['income']) if m in fee_map else 0 for m in months],
            'monthly_expense': [float(fee_map[m]['expense']) if m in fee_map else 0 for m in months],
            'monthly_payments': [pay_map.get(m, 0) for m in months],
        },
        'chart_mode': 'cash_flow',
        'table_columns': ['月份', '费用收入', '费用支出', '销售回款', '累计收入', '累计支出', '累计回款'],
        'table_rows': table_rows,
        'export_rows': table_rows,
    }


def _business_alerts(db, filters):
    from client_collab_scope import (
        COLLAB_FUNDS_REPORT_ROLES,
        get_assigned_customer_ids,
    )
    role = filters.get('_scope_role', '')
    user_id = filters.get('_scope_user_id')
    alerts = []

    over_budget = db.execute("""
        SELECT p.id, p.name, COALESCE(p.budget,0) as budget,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END),0) as expense
        FROM projects p
        LEFT JOIN transaction_records t ON p.id = t.project_id
        WHERE COALESCE(p.budget,0) > 0
        GROUP BY p.id
        HAVING expense > budget
    """).fetchall()
    for r in over_budget:
        alerts.append({
            '类型': '预算超支',
            '对象': r['name'],
            '说明': f'支出 {float(r["expense"]):.2f} > 预算 {float(r["budget"]):.2f}',
            '链接': f'/project/{r["id"]}',
            '链接文字': '查看项目',
        })

    unpaid = db.execute("""
        SELECT so.id, so.order_no, so.customer_name, so.order_date, so.total_amount, so.status
        FROM sales_orders so
        WHERE so.total_amount > 0
    """).fetchall()
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    for r in unpaid:
        total = float(r['total_amount'] or 0)
        st = (r['status'] or '')
        if r['order_date'] and str(r['order_date'])[:10] <= cutoff and st not in ('已完成', 'completed', '已关闭'):
            alerts.append({
                '类型': '长期未回款',
                '对象': r['order_no'] or str(r['id']),
                '说明': f'{r["customer_name"] or "-"} 订单额 {total:.2f}，订单日 {r["order_date"]}',
                '链接': f'/sales/order/{r["id"]}',
                '链接文字': '查看订单',
            })

    po_date_col = purchase_date_column(db)
    pending_po = db.execute(f"""
        SELECT id, purchase_no, supplier, {po_date_col} as po_date, status FROM purchase_orders
        WHERE status IN ('submitted', 'partial', '已提交', '部分到货', '待对账')
        ORDER BY id DESC LIMIT 50
    """).fetchall()
    for r in pending_po:
        alerts.append({
            '类型': '待对账采购',
            '对象': r['purchase_no'] or str(r['id']),
            '说明': f'{r["supplier"] or "-"} {r["status"]} {r["po_date"] or ""}',
            '链接': '/reconciliation/list',
            '链接文字': '对账中心',
        })

    if role in COLLAB_FUNDS_REPORT_ROLES:
        allowed = get_assigned_customer_ids(db, user_id, role)
        lb_sql = """
            SELECT ca.id, ca.customer_id, ca.company_name, ca.balance, ca.alert_threshold
            FROM client_accounts ca
            WHERE ca.status IN ('approved', 'active')
              AND ca.balance < COALESCE(ca.alert_threshold, 5000)
        """
        lb_params = []
        if allowed is not None:
            if not allowed:
                low_balance = []
            else:
                ph = ','.join('?' * len(allowed))
                lb_sql += f' AND ca.customer_id IN ({ph})'
                lb_params = list(allowed)
                low_balance = db.execute(
                    lb_sql + ' ORDER BY ca.balance ASC LIMIT 30', lb_params
                ).fetchall()
        else:
            low_balance = db.execute(
                lb_sql + ' ORDER BY ca.balance ASC LIMIT 30', lb_params
            ).fetchall()
        for r in low_balance:
            thresh = float(r['alert_threshold'] or 5000)
            cid = r['customer_id'] or 0
            alerts.append({
                '类型': '客户余额偏低',
                '对象': r['company_name'] or str(r['id']),
                '说明': f'余额 {float(r["balance"]):.2f} < 阈值 {thresh:.2f}',
                '链接': f'/admin/client-company/{cid}' if cid else '/admin/client-accounts',
                '链接文字': '协同工作台',
            })

    return {
        'kpis': [
            {'label': '预警条数', 'value': str(len(alerts)), 'border': 'danger'},
            {'label': '预算超支', 'value': str(len(over_budget)), 'border': 'warning'},
            {'label': '低余额客户', 'value': str(len(low_balance)), 'border': 'info'},
        ],
        'chart_data': {},
        'chart_mode': 'none',
        'table_columns': ['类型', '对象', '说明', '链接文字'],
        'table_rows': alerts,
        'export_rows': [{k: v for k, v in a.items() if k != '链接'} for a in alerts],
        'alert_links': True,
    }


def _fee_profit(db, filters):
    tp, par = _trans_filters(filters, 't')
    w, p = _where(tp, par)

    summary = db.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as total_expense,
            COUNT(*) as record_count
        FROM transaction_records t {w}
    """, p).fetchone()

    total_income = float(summary['total_income'] or 0)
    total_expense = float(summary['total_expense'] or 0)
    total_profit = total_income - total_expense
    profit_rate = (total_profit / total_income * 100) if total_income > 0 else 0

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', t.trans_date) as month,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as expense
        FROM transaction_records t {w}
        GROUP BY month ORDER BY month
    """, p).fetchall()

    join_extra = (' AND ' + ' AND '.join(tp)) if tp else ''
    cat_stats = db.execute(f"""
        SELECT c.name, c.type, COALESCE(SUM(t.amount), 0) as total
        FROM categories c
        INNER JOIN transaction_records t ON c.id = t.category_id{join_extra}
        GROUP BY c.id HAVING total > 0
        ORDER BY total DESC
    """, p).fetchall()

    income_by_category = [
        {'name': r['name'], 'value': float(r['total'])}
        for r in cat_stats if r['type'] == 'income'
    ]
    expense_by_category = [
        {'name': r['name'], 'value': float(r['total'])}
        for r in cat_stats if r['type'] == 'expense'
    ]

    project_summary = db.execute("""
        SELECT p.id, p.name, COALESCE(p.budget,0) as budget,
            COALESCE(SUM(CASE WHEN t.trans_type='income' THEN t.amount ELSE 0 END), 0) as income,
            COALESCE(SUM(CASE WHEN t.trans_type='expense' THEN t.amount ELSE 0 END), 0) as expense,
            COUNT(t.id) as record_count
        FROM projects p
        LEFT JOIN transaction_records t ON p.id = t.project_id
        GROUP BY p.id ORDER BY p.name
    """).fetchall()

    proj_rows = []
    for ps in project_summary:
        inc = float(ps['income'] or 0)
        exp = float(ps['expense'] or 0)
        bud = float(ps['budget'] or 0)
        proj_rows.append({
            '项目': ps['name'],
            '预算': f'{bud:.2f}',
            '收入': f'{inc:.2f}',
            '支出': f'{exp:.2f}',
            '利润': f'{inc - exp:.2f}',
            '笔数': ps['record_count'],
        })

    chart_data = {
        'income_by_category': income_by_category or [{'name': '无数据', 'value': 0}],
        'expense_by_category': expense_by_category or [{'name': '无数据', 'value': 0}],
        'monthly_labels': [r['month'] for r in monthly if r['month']],
        'monthly_income': [float(r['income']) for r in monthly if r['month']],
        'monthly_expense': [float(r['expense']) for r in monthly if r['month']],
    }

    return {
        'kpis': [
            {'label': '总收入', 'value': f'{total_income:.2f}', 'border': 'success'},
            {'label': '总支出', 'value': f'{total_expense:.2f}', 'border': 'danger'},
            {'label': '利润', 'value': f'{total_profit:.2f}', 'border': 'primary'},
            {'label': '毛利率', 'value': f'{profit_rate:.2f}%', 'border': 'warning'},
        ],
        'chart_data': chart_data,
        'chart_mode': 'fee_profit',
        'project_summary': project_summary,
        'table_columns': ['项目', '预算', '收入', '支出', '利润', '笔数'],
        'table_rows': proj_rows,
        'export_rows': proj_rows,
        'summary': summary,
        'total_profit': total_profit,
        'profit_rate': profit_rate,
    }


def _fee_category(db, filters):
    pid = filters.get('project_id') or None
    tree = build_category_tree(
        db, pid,
        date_from=filters.get('date_from') or None,
        date_to=filters.get('date_to') or None,
    )

    expense_top = []
    def flatten_expense(nodes, depth=0):
        for n in nodes:
            if n['total'] > 0:
                expense_top.append({'name': n['name'], 'value': float(n['total'])})
            flatten_expense(n.get('children', []), depth + 1)

    flatten_expense(tree.get('expense', []))
    expense_top.sort(key=lambda x: x['value'], reverse=True)
    expense_top = expense_top[:15]

    return {
        'kpis': [
            {'label': '支出科目数', 'value': str(len(expense_top)), 'border': 'danger'},
            {'label': '支出合计', 'value': f'{sum(x["value"] for x in expense_top):.2f}', 'border': 'warning'},
        ],
        'chart_data': {
            'expense_top_labels': [x['name'] for x in expense_top],
            'expense_top_values': [x['value'] for x in expense_top],
        },
        'chart_mode': 'fee_category',
        'category_tree': tree,
        'table_columns': [],
        'table_rows': [],
        'export_rows': [
            {'科目': x['name'], '金额': x['value']} for x in expense_top
        ],
    }


def _sales_outbound(db, filters):
    so_p, so_par = _sales_order_filters(filters, 'so')
    so_w, so_params = _where(so_p, so_par)

    summary = db.execute(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt,
               COALESCE(SUM(total_quantity),0) as qty
        FROM sales_orders so {so_w}
    """, so_params).fetchone()

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', so.order_date) as month,
            COALESCE(SUM(so.total_amount),0) as amt,
            COALESCE(SUM(so.total_quantity),0) as qty
        FROM sales_orders so {so_w}
        GROUP BY month ORDER BY month
    """, so_params).fetchall()

    by_customer = db.execute(f"""
        SELECT so.customer_name as name,
            COALESCE(SUM(so.total_amount),0) as amt,
            COALESCE(SUM(so.total_quantity),0) as qty,
            COUNT(*) as cnt
        FROM sales_orders so {so_w}
        GROUP BY so.customer_name ORDER BY amt DESC LIMIT 10
    """, so_params).fetchall()

    detail = db.execute(f"""
        SELECT strftime('%Y-%m', so.order_date) as month, so.customer_name,
            COALESCE(SUM(so.total_amount),0) as amt,
            COALESCE(SUM(so.total_quantity),0) as qty
        FROM sales_orders so {so_w}
        GROUP BY month, so.customer_name ORDER BY month DESC, amt DESC
    """, so_params).fetchall()

    table_rows = [
        {
            '月份': r['month'] or '-',
            '客户': r['customer_name'] or '-',
            '销售金额': f'{float(r["amt"]):.2f}',
            '销售吨数': f'{float(r["qty"]):.2f}',
        }
        for r in detail
    ]

    return {
        'kpis': [
            {'label': '订单数', 'value': str(summary['cnt']), 'border': 'primary'},
            {'label': '销售吨数', 'value': f'{float(summary["qty"]):.2f}', 'border': 'info'},
            {'label': '销售金额', 'value': f'{float(summary["amt"]):.2f}', 'border': 'success'},
        ],
        'chart_data': {
            'monthly_labels': [r['month'] for r in monthly if r['month']],
            'monthly_amount': [float(r['amt']) for r in monthly if r['month']],
            'monthly_qty': [float(r['qty']) for r in monthly if r['month']],
            'customer_labels': [(r['name'] or '未知')[:10] for r in by_customer],
            'customer_amount': [float(r['amt']) for r in by_customer],
        },
        'chart_mode': 'sales_outbound',
        'table_columns': ['月份', '客户', '销售金额', '销售吨数'],
        'table_rows': table_rows,
        'export_rows': table_rows,
        'footnote': '销售金额取自销售订单 total_amount。',
    }


def _sales_outbound_detail_lines(db, filters):
    """拉取出库单明细行（含整单运费、运输数量）。"""
    so_p, so_par = _sales_order_filters(filters, 'so')
    parts = list(so_p)
    params = list(so_par)
    if filters.get('item_name'):
        parts.append('soi.item_name LIKE ?')
        params.append(f'%{filters["item_name"]}%')
    if filters.get('specification'):
        parts.append('soi.specification LIKE ?')
        params.append(f'%{filters["specification"]}%')
    so_w, bind = _where(parts, params)
    join_on = _sales_item_order_join(db)
    rows = db.execute(f"""
        SELECT so.id as order_id, so.order_no, so.order_date, so.customer_name, so.status,
               p.name as project_name,
               soi.item_name, soi.specification, soi.unit,
               COALESCE(soi.quantity, 0) as quantity,
               COALESCE(soi.unit_price, 0) as unit_price,
               COALESCE(soi.amount, 0) as amount
        FROM sales_orders so
        INNER JOIN sales_order_items soi ON {join_on}
        LEFT JOIN projects p ON so.project_id = p.id
        {so_w}
        ORDER BY so.order_date DESC, so.order_no, COALESCE(soi.sort_order, 0), soi.id
    """, bind).fetchall()
    lines = [dict(r) for r in rows]
    order_ids = list({r['order_id'] for r in lines if r.get('order_id') is not None})
    transport_totals = _sales_transport_totals_map(db, order_ids)
    for r in lines:
        t = transport_totals.get(int(r['order_id']), {'freight': 0.0, 'qty': 0.0})
        r['order_freight'] = t['freight']
        r['transport_qty'] = t['qty']
    return lines


def _aggregate_sales_outbound_lines(lines, group_by):
    if group_by == 'detail' or not lines:
        return None

    def bucket_key(r):
        if group_by == 'customer':
            return r.get('customer_name') or '未知'
        if group_by == 'item_name':
            return r.get('item_name') or '未知'
        if group_by == 'specification':
            return r.get('specification') or '-'
        if group_by == 'item_spec':
            return f"{r.get('item_name') or '未知'} / {r.get('specification') or '-'}"
        if group_by == 'date_day':
            d = (r.get('order_date') or '')[:10]
            return d or '未知'
        if group_by == 'date_month':
            d = (r.get('order_date') or '')[:7]
            return d or '未知'
        if group_by == 'project':
            return r.get('project_name') or '未知'
        return '未知'

    buckets = {}
    for r in lines:
        key = bucket_key(r)
        b = buckets.setdefault(key, {
            'dim': key,
            'line_cnt': 0,
            'order_ids': set(),
            'qty': 0.0,
            'amt': 0.0,
            'freight': 0.0,
            'transport_qty': 0.0,
        })
        b['line_cnt'] += 1
        b['qty'] += float(r.get('quantity') or 0)
        b['amt'] += float(r.get('amount') or 0)
        oid = r.get('order_id')
        if oid is not None and oid not in b['order_ids']:
            b['order_ids'].add(oid)
            b['freight'] += float(r.get('order_freight') or 0)
            b['transport_qty'] += float(r.get('transport_qty') or 0)

    result = sorted(buckets.values(), key=lambda x: (-x['amt'], x['dim']))
    for b in result:
        b['order_cnt'] = len(b['order_ids'])
        del b['order_ids']
    return result


def _sales_outbound_detail(db, filters):
    group_by = filters.get('group_by') or 'detail'
    if group_by not in SALES_OUTBOUND_GROUP_LABELS:
        group_by = 'detail'

    lines = _sales_outbound_detail_lines(db, filters)
    order_ids = {r['order_id'] for r in lines if r.get('order_id') is not None}
    total_freight = 0.0
    total_transport_qty = 0.0
    seen_freight_orders = set()
    for r in lines:
        oid = r.get('order_id')
        if oid in seen_freight_orders:
            continue
        seen_freight_orders.add(oid)
        total_freight += float(r.get('order_freight') or 0)
        total_transport_qty += float(r.get('transport_qty') or 0)

    total_qty = sum(float(r.get('quantity') or 0) for r in lines)
    total_amt = sum(float(r.get('amount') or 0) for r in lines)

    group_label = SALES_OUTBOUND_GROUP_LABELS.get(group_by, group_by)
    table_footer = None

    if group_by == 'detail':
        table_columns = [
            '出库单号', '出库日期', '客户', '项目', '状态',
            '品名', '规格型号', '单位', '数量', '单价', '明细金额',
            '整单运费', '运输数量',
        ]
        table_rows = [
            {
                '出库单号': r.get('order_no') or '-',
                '出库日期': (r.get('order_date') or '-')[:10],
                '客户': r.get('customer_name') or '-',
                '项目': r.get('project_name') or '-',
                '状态': r.get('status') or '-',
                '品名': r.get('item_name') or '-',
                '规格型号': r.get('specification') or '-',
                '单位': r.get('unit') or '-',
                '数量': f'{float(r.get("quantity") or 0):.2f}',
                '单价': f'{float(r.get("unit_price") or 0):.2f}',
                '明细金额': f'{float(r.get("amount") or 0):.2f}',
                '整单运费': f'{float(r.get("order_freight") or 0):.2f}',
                '运输数量': f'{float(r.get("transport_qty") or 0):.2f}',
            }
            for r in lines
        ]
        table_footer = {
            '出库单号': '合计',
            '出库日期': f'{len(order_ids)} 单 · {len(lines)} 行',
            '客户': '',
            '项目': '',
            '状态': '',
            '品名': '',
            '规格型号': '',
            '单位': '',
            '数量': f'{total_qty:.2f}',
            '单价': '',
            '明细金额': f'{total_amt:.2f}',
            '整单运费': f'{total_freight:.2f}',
            '运输数量': f'{total_transport_qty:.2f}',
        }
    else:
        agg = _aggregate_sales_outbound_lines(lines, group_by)
        dim_title = {
            'customer': '客户',
            'item_name': '品名',
            'specification': '规格型号',
            'item_spec': '品名/规格',
            'date_day': '出库日期',
            'date_month': '月份',
            'project': '项目',
        }.get(group_by, '维度')
        table_columns = [
            dim_title, '出库单数', '明细行数', '销售数量', '明细金额合计', '运费合计', '运输数量合计',
        ]
        table_rows = [
            {
                dim_title: b['dim'],
                '出库单数': str(b['order_cnt']),
                '明细行数': str(b['line_cnt']),
                '销售数量': f'{b["qty"]:.2f}',
                '明细金额合计': f'{b["amt"]:.2f}',
                '运费合计': f'{b["freight"]:.2f}',
                '运输数量合计': f'{b["transport_qty"]:.2f}',
            }
            for b in (agg or [])
        ]
        if agg:
            table_footer = {
                dim_title: '合计',
                '出库单数': str(len(order_ids)),
                '明细行数': str(len(lines)),
                '销售数量': f'{total_qty:.2f}',
                '明细金额合计': f'{total_amt:.2f}',
                '运费合计': f'{total_freight:.2f}',
                '运输数量合计': f'{total_transport_qty:.2f}',
            }

    # 汇总图表：按客户 Top10（明细金额）
    by_customer = {}
    for r in lines:
        name = r.get('customer_name') or '未知'
        by_customer[name] = by_customer.get(name, 0.0) + float(r.get('amount') or 0)
    top_customers = sorted(by_customer.items(), key=lambda x: -x[1])[:10]

    return {
        'kpis': [
            {'label': '出库单数', 'value': str(len(order_ids)), 'border': 'primary'},
            {'label': '明细行数', 'value': str(len(lines)), 'border': 'info'},
            {'label': '销售数量', 'value': f'{total_qty:.2f}', 'border': 'secondary'},
            {'label': '明细金额', 'value': f'{total_amt:.2f}', 'border': 'success'},
            {'label': '运费合计', 'value': f'{total_freight:.2f}', 'border': 'warning'},
            {'label': '运输数量合计', 'value': f'{total_transport_qty:.2f}', 'border': 'info'},
        ],
        'chart_data': {
            'customer_labels': [x[0][:12] for x in top_customers],
            'customer_amount': [round(x[1], 2) for x in top_customers],
        },
        'chart_mode': 'sales_outbound_detail',
        'table_columns': table_columns,
        'table_rows': table_rows,
        'table_footer': table_footer,
        'export_rows': table_rows + ([table_footer] if table_footer else []),
        'group_by': group_by,
        'group_label': group_label,
        'footnote': (
            f'当前汇总方式：{group_label}。明细金额来自销售出库明细；运费按出库单关联运输记录汇总，'
            '汇总模式下运费按出库单去重累计（同一单不重复计运费）。'
            '表尾合计中整单运费、运输数量为按出库单去重后的合计（与逐行显示可能不同）。',
        ),
    }


PTS_GROUP_LABELS = {
    'detail': '明细（项目+品名+规格）',
    'item_spec': '按品名+规格汇总',
    'item_name': '按品名汇总',
    'specification': '按规格型号汇总',
    'project': '按项目汇总',
    'supplier': '按供应商汇总',
    'customer': '按客户汇总',
    'date_month': '按月份汇总',
}


def _pts_is_purchase_draft(status):
    return (status or '').strip() in ('draft', '草稿')


def _pts_is_sales_draft(status):
    return (status or '').strip() in ('待审核', 'pending', '待处理', 'draft', '草稿')


def _pts_bucket_factory():
    return {
        'purchase_qty': 0.0,
        'purchase_amt': 0.0,
        'freight_qty': 0.0,
        'freight_amt': 0.0,
        'sales_qty': 0.0,
        'sales_amt': 0.0,
        'supplier': '',
        'customer': '',
    }


def _pts_detail_key(row):
    return (
        row.get('project_name') or '未知',
        row.get('item_name') or '未知',
        row.get('specification') or '-',
    )


def _pts_row_key(row, group_by):
    if group_by == 'date_month':
        m = (row.get('biz_month') or '')[:7]
        return (m or '未知',)
    return _pts_detail_key(row)


def _pts_group_key(row, group_by):
    if group_by == 'detail' or group_by == 'item_spec':
        return _pts_detail_key(row)
    if group_by == 'item_name':
        return (row.get('item_name') or '未知',)
    if group_by == 'specification':
        return (row.get('specification') or '-',)
    if group_by == 'project':
        return (row.get('project_name') or '未知',)
    if group_by == 'supplier':
        return (row.get('supplier') or '未知',)
    if group_by == 'customer':
        return (row.get('customer') or '未知',)
    if group_by == 'date_month':
        return (row.get('month') or '未知',)
    return _pts_detail_key(row)


def _pts_load_purchase_buckets(db, filters, buckets, include_draft, group_by):
    po_date_col = purchase_date_column(db)
    po_p, po_par = _purchase_filters(filters, 'po', po_date_col)
    parts = list(po_p)
    params = list(po_par)
    if filters.get('item_name'):
        parts.append('pi.item_name LIKE ?')
        params.append(f'%{filters["item_name"]}%')
    if filters.get('specification'):
        parts.append('pi.specification LIKE ?')
        params.append(f'%{filters["specification"]}%')
    po_w, bind = _where(parts, params)
    rows = db.execute(f"""
        SELECT p.name as project_name, pi.item_name, pi.specification, po.supplier,
               COALESCE(pi.quantity, 0) as qty, COALESCE(pi.amount, 0) as amt, po.status,
               po.{po_date_col} as biz_month
        FROM purchase_items pi
        JOIN purchase_orders po ON pi.purchase_id = po.id
        LEFT JOIN projects p ON po.project_id = p.id
        {po_w}
    """, bind).fetchall()
    for r in rows:
        if not include_draft and _pts_is_purchase_draft(r['status']):
            continue
        row = dict(r)
        key = _pts_row_key(row, group_by)
        b = buckets[key]
        b['purchase_qty'] += float(r['qty'] or 0)
        b['purchase_amt'] += float(r['amt'] or 0)
        if r['supplier'] and not b['supplier']:
            b['supplier'] = r['supplier']


def _pts_load_sales_buckets(db, filters, buckets, include_draft, group_by):
    so_p, so_par = _sales_order_filters(filters, 'so')
    parts = list(so_p)
    params = list(so_par)
    if filters.get('item_name'):
        parts.append('soi.item_name LIKE ?')
        params.append(f'%{filters["item_name"]}%')
    if filters.get('specification'):
        parts.append('soi.specification LIKE ?')
        params.append(f'%{filters["specification"]}%')
    so_w, bind = _where(parts, params)
    join_on = _sales_item_order_join(db)
    rows = db.execute(f"""
        SELECT p.name as project_name, soi.item_name, soi.specification,
               so.customer_name as customer,
               COALESCE(soi.quantity, 0) as qty, COALESCE(soi.amount, 0) as amt, so.status,
               so.order_date as biz_month
        FROM sales_orders so
        INNER JOIN sales_order_items soi ON {join_on}
        LEFT JOIN projects p ON so.project_id = p.id
        {so_w}
    """, bind).fetchall()
    for r in rows:
        if not include_draft and _pts_is_sales_draft(r['status']):
            continue
        row = dict(r)
        key = _pts_row_key(row, group_by)
        b = buckets[key]
        b['sales_qty'] += float(r['qty'] or 0)
        b['sales_amt'] += float(r['amt'] or 0)
        if r['customer'] and not b['customer']:
            b['customer'] = r['customer']


def _pts_allocate_transport(db, filters, buckets, include_draft, group_by):
    """将运输记录数量、运费分摊到品名维度（采购明细关联 / 销售明细关联 / 整单分摊）。"""
    tr_p, tr_par = _transport_filters(filters, 'tr')
    tr_w, tr_bind = _where(tr_p, tr_par)
    transports = db.execute(f"""
        SELECT tr.id, tr.purchase_id, tr.sales_order_id, tr.quantity, tr.freight_amount,
               tr.transport_date as biz_month
        FROM transport_records tr {tr_w}
    """, tr_bind).fetchall()

    for tr in transports:
        tid = tr['id']
        t_qty = float(tr['quantity'] or 0)
        t_freight = float(tr['freight_amount'] or 0)
        if t_qty == 0 and t_freight == 0:
            continue

        links = []

        tpi_rows = db.execute("""
            SELECT pi.item_name, pi.specification, p.name as project_name, po.supplier, po.status,
                   COALESCE(NULLIF(tpi.quantity, 0), 0) as link_qty
            FROM transport_purchase_items tpi
            JOIN purchase_items pi ON tpi.purchase_item_id = pi.id
            JOIN purchase_orders po ON pi.purchase_id = po.id
            LEFT JOIN projects p ON po.project_id = p.id
            WHERE tpi.transport_id = ?
        """, (tid,)).fetchall()
        for row in tpi_rows:
            if not include_draft and _pts_is_purchase_draft(row['status']):
                continue
            links.append({
                'project_name': row['project_name'],
                'item_name': row['item_name'],
                'specification': row['specification'],
                'biz_month': tr['biz_month'],
                'weight': float(row['link_qty'] or 0),
            })

        if not links and tr['purchase_id']:
            po_row = db.execute(
                f"""SELECT po.status FROM purchase_orders po WHERE po.id = ?""",
                (tr['purchase_id'],),
            ).fetchone()
            if include_draft or not (po_row and _pts_is_purchase_draft(po_row['status'])):
                pi_rows = db.execute("""
                    SELECT pi.item_name, pi.specification, p.name as project_name,
                           COALESCE(pi.quantity, 0) as link_qty
                    FROM purchase_items pi
                    JOIN purchase_orders po ON pi.purchase_id = po.id
                    LEFT JOIN projects p ON po.project_id = p.id
                    WHERE po.id = ?
                """, (tr['purchase_id'],)).fetchall()
                for row in pi_rows:
                    links.append({
                        'project_name': row['project_name'],
                        'item_name': row['item_name'],
                        'specification': row['specification'],
                        'biz_month': tr['biz_month'],
                        'weight': float(row['link_qty'] or 0),
                    })

        join_so = _sales_item_order_join(db)
        sit_rows = db.execute(f"""
            SELECT soi.item_name, soi.specification, p.name as project_name,
                   so.customer_name as customer, so.status,
                   COALESCE(NULLIF(sit.quantity, 0), 0) as link_qty
            FROM sales_item_transport sit
            JOIN sales_order_items soi ON sit.sales_item_id = soi.id
            JOIN sales_orders so ON {join_so}
            LEFT JOIN projects p ON so.project_id = p.id
            WHERE sit.transport_id = ?
        """, (tid,)).fetchall()
        for row in sit_rows:
            if not include_draft and _pts_is_sales_draft(row['status']):
                continue
            links.append({
                'project_name': row['project_name'],
                'item_name': row['item_name'],
                'specification': row['specification'],
                'biz_month': tr['biz_month'],
                'weight': float(row['link_qty'] or 0),
            })

        if not links and tr['sales_order_id']:
            tr_cols = {r[1] for r in db.execute('PRAGMA table_info(transport_records)').fetchall()}
            if 'sales_order_id' in tr_cols:
                so_row = db.execute(
                    'SELECT status FROM sales_orders WHERE id = ?', (tr['sales_order_id'],)
                ).fetchone()
                if include_draft or not (so_row and _pts_is_sales_draft(so_row['status'])):
                    soi_rows = db.execute(f"""
                        SELECT soi.item_name, soi.specification, p.name as project_name,
                               COALESCE(soi.quantity, 0) as link_qty
                        FROM sales_order_items soi
                        JOIN sales_orders so ON {join_so}
                        LEFT JOIN projects p ON so.project_id = p.id
                        WHERE so.id = ?
                    """, (tr['sales_order_id'],)).fetchall()
                    for row in soi_rows:
                        links.append({
                            'project_name': row['project_name'],
                            'item_name': row['item_name'],
                            'specification': row['specification'],
                            'biz_month': tr['biz_month'],
                            'weight': float(row['link_qty'] or 0),
                        })

        if not links:
            continue

        total_w = sum(l['weight'] for l in links) or t_qty or 1.0
        for link in links:
            share = (link['weight'] / total_w) if total_w else 0
            key = _pts_row_key(link, group_by)
            b = buckets[key]
            b['freight_qty'] += t_qty * share
            b['freight_amt'] += t_freight * share


def _pts_build_detail_buckets(db, filters, group_by):
    from collections import defaultdict
    include_draft = filters.get('include_draft', True)
    buckets = defaultdict(_pts_bucket_factory)
    _pts_load_purchase_buckets(db, filters, buckets, include_draft, group_by)
    _pts_load_sales_buckets(db, filters, buckets, include_draft, group_by)
    _pts_allocate_transport(db, filters, buckets, include_draft, group_by)
    return buckets


def _pts_aggregate_buckets(buckets, group_by):
    from collections import defaultdict
    if group_by == 'detail':
        return dict(buckets)
    grouped = defaultdict(_pts_bucket_factory)
    for key, b in buckets.items():
        row = {
            'project_name': key[0] if len(key) > 0 else '未知',
            'item_name': key[1] if len(key) > 1 else (key[0] if group_by == 'item_name' else '未知'),
            'specification': key[2] if len(key) > 2 else (key[1] if group_by == 'specification' else '-'),
            'supplier': b.get('supplier') or '',
            'customer': b.get('customer') or '',
            'month': '',
        }
        gk = _pts_group_key(row, group_by)
        g = grouped[gk]
        for field in ('purchase_qty', 'purchase_amt', 'freight_qty', 'freight_amt', 'sales_qty', 'sales_amt'):
            g[field] += b[field]
        if b.get('supplier') and not g['supplier']:
            g['supplier'] = b['supplier']
        if b.get('customer') and not g['customer']:
            g['customer'] = b['customer']
    return dict(grouped)


def _pts_row_to_table(dim_label, dim_value, b, extra=None):
    row = {
        dim_label: dim_value,
        '采购数量': f'{b["purchase_qty"]:.2f}',
        '采购金额': f'{b["purchase_amt"]:.2f}',
        '运费数量': f'{b["freight_qty"]:.2f}',
        '运费金额': f'{b["freight_amt"]:.2f}',
        '出库数量': f'{b["sales_qty"]:.2f}',
        '出库金额': f'{b["sales_amt"]:.2f}',
    }
    if extra:
        row.update(extra)
    return row


def _pts_summary_detail(db, filters):
    group_by = filters.get('group_by') or 'detail'
    if group_by not in PTS_GROUP_LABELS:
        group_by = 'detail'

    raw = _pts_build_detail_buckets(db, filters, group_by)
    agg = _pts_aggregate_buckets(raw, group_by) if group_by != 'date_month' else raw
    group_label = PTS_GROUP_LABELS[group_by]

    dim_labels = {
        'detail': '维度',
        'item_spec': '品名/规格',
        'item_name': '品名',
        'specification': '规格型号',
        'project': '项目',
        'supplier': '供应商',
        'customer': '客户',
        'date_month': '月份',
    }
    dim_col = dim_labels.get(group_by, '维度')

    table_columns = [dim_col, '采购数量', '采购金额', '运费数量', '运费金额', '出库数量', '出库金额']
    if group_by == 'detail':
        table_columns = [
            '项目', '品名', '规格型号', '供应商', '客户',
            '采购数量', '采购金额', '运费数量', '运费金额', '出库数量', '出库金额',
        ]

    table_rows = []
    sorted_items = sorted(
        agg.items(),
        key=lambda x: (-(x[1]['purchase_amt'] + x[1]['sales_amt']), str(x[0])),
    )

    for key, b in sorted_items:
        if group_by == 'detail':
            table_rows.append({
                '项目': key[0],
                '品名': key[1],
                '规格型号': key[2],
                '供应商': b.get('supplier') or '-',
                '客户': b.get('customer') or '-',
                '采购数量': f'{b["purchase_qty"]:.2f}',
                '采购金额': f'{b["purchase_amt"]:.2f}',
                '运费数量': f'{b["freight_qty"]:.2f}',
                '运费金额': f'{b["freight_amt"]:.2f}',
                '出库数量': f'{b["sales_qty"]:.2f}',
                '出库金额': f'{b["sales_amt"]:.2f}',
            })
        else:
            dim_val = key[0] if isinstance(key, tuple) and len(key) == 1 else (
                ' / '.join(str(k) for k in key) if isinstance(key, tuple) else str(key)
            )
            table_rows.append(_pts_row_to_table(dim_col, dim_val, b))

    totals = {
        'purchase_qty': sum(b['purchase_qty'] for b in agg.values()),
        'purchase_amt': sum(b['purchase_amt'] for b in agg.values()),
        'freight_qty': sum(b['freight_qty'] for b in agg.values()),
        'freight_amt': sum(b['freight_amt'] for b in agg.values()),
        'sales_qty': sum(b['sales_qty'] for b in agg.values()),
        'sales_amt': sum(b['sales_amt'] for b in agg.values()),
    }

    table_footer = None
    if table_rows:
        if group_by == 'detail':
            table_footer = {
                '项目': '合计',
                '品名': f'{len(table_rows)} 项',
                '规格型号': '',
                '供应商': '',
                '客户': '',
                '采购数量': f'{totals["purchase_qty"]:.2f}',
                '采购金额': f'{totals["purchase_amt"]:.2f}',
                '运费数量': f'{totals["freight_qty"]:.2f}',
                '运费金额': f'{totals["freight_amt"]:.2f}',
                '出库数量': f'{totals["sales_qty"]:.2f}',
                '出库金额': f'{totals["sales_amt"]:.2f}',
            }
        else:
            table_footer = _pts_row_to_table(dim_col, '合计', totals)

    return {
        'kpis': [
            {'label': '采购金额', 'value': f'{totals["purchase_amt"]:.2f}', 'border': 'primary'},
            {'label': '采购数量', 'value': f'{totals["purchase_qty"]:.2f}', 'border': 'info'},
            {'label': '运费金额', 'value': f'{totals["freight_amt"]:.2f}', 'border': 'warning'},
            {'label': '运费数量', 'value': f'{totals["freight_qty"]:.2f}', 'border': 'secondary'},
            {'label': '出库金额', 'value': f'{totals["sales_amt"]:.2f}', 'border': 'success'},
            {'label': '出库数量', 'value': f'{totals["sales_qty"]:.2f}', 'border': 'success'},
        ],
        'chart_data': {},
        'chart_mode': 'none',
        'table_columns': table_columns,
        'table_rows': table_rows,
        'table_footer': table_footer,
        'export_rows': table_rows + ([table_footer] if table_footer else []),
        'group_by': group_by,
        'group_label': group_label,
        'footnote': (
            f'当前汇总：{group_label}。采购取自采购单明细；运费取自运输记录并按明细关联分摊；'
            '出库取自销售出库单明细（客户端入库口径）。'
            '未勾选「含未提交」时排除草稿/待审核单据。'
        ),
    }


def _sales_collection(db, filters):
    so_p, so_par = _sales_order_filters(filters, 'so')
    so_w, so_params = _where(so_p, so_par)
    pay_cust_col = payment_customer_column(db)

    orders_total = db.execute(f"""
        SELECT COALESCE(SUM(total_amount),0) as amt FROM sales_orders so {so_w}
    """, so_params).fetchone()['amt']

    pay_p, pay_par = _payment_filters(filters, 'sp', pay_cust_col)
    pay_w, pay_params = _where(pay_p, pay_par)
    paid_total = db.execute(f"""
        SELECT COALESCE(SUM(amount),0) as amt FROM sales_payments sp {pay_w}
    """, pay_params).fetchone()['amt']

    orders_total = float(orders_total or 0)
    paid_total = float(paid_total or 0)
    rate = (paid_total / orders_total * 100) if orders_total > 0 else 0

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', sp.payment_date) as month,
            COALESCE(SUM(sp.amount),0) as amt
        FROM sales_payments sp {pay_w}
        GROUP BY month ORDER BY month
    """, pay_params).fetchall()

    order_by_cust = db.execute(f"""
        SELECT so.customer_name as name, COALESCE(SUM(so.total_amount),0) as order_amt
        FROM sales_orders so {so_w}
        GROUP BY so.customer_name ORDER BY order_amt DESC LIMIT 50
    """, so_params).fetchall()

    pay_by_cust = {}
    pay_rows = db.execute(f"""
        SELECT sp.{pay_cust_col} as name, COALESCE(SUM(sp.amount),0) as paid_amt,
            MAX(sp.payment_date) as last_pay
        FROM sales_payments sp {pay_w}
        GROUP BY sp.{pay_cust_col}
    """, pay_params).fetchall()
    for pr in pay_rows:
        pay_by_cust[pr['name'] or ''] = pr

    table_rows = []
    seen = set()
    for r in order_by_cust:
        name = r['name'] or '-'
        seen.add(name)
        oa = float(r['order_amt'] or 0)
        pr = pay_by_cust.get(r['name'] or '', {})
        pa = float(pr['paid_amt'] if pr else 0)
        table_rows.append({
            '客户': name,
            '订单额': f'{oa:.2f}',
            '已回款': f'{pa:.2f}',
            '未回款': f'{max(0, oa - pa):.2f}',
            '最近回款日': (pr['last_pay'] if pr else None) or '-',
        })
    for name, pr in pay_by_cust.items():
        if name in seen or not name:
            continue
        pa = float(pr['paid_amt'] or 0)
        table_rows.append({
            '客户': name,
            '订单额': '0.00',
            '已回款': f'{pa:.2f}',
            '未回款': '0.00',
            '最近回款日': pr['last_pay'] or '-',
        })

    return {
        'kpis': [
            {'label': '订单应收', 'value': f'{orders_total:.2f}', 'border': 'warning'},
            {'label': '已回款', 'value': f'{paid_total:.2f}', 'border': 'success'},
            {'label': '回款率', 'value': f'{rate:.1f}%', 'border': 'primary'},
        ],
        'chart_data': {
            'monthly_labels': [r['month'] for r in monthly if r['month']],
            'monthly_payments': [float(r['amt']) for r in monthly if r['month']],
        },
        'chart_mode': 'sales_collection',
        'table_columns': ['客户', '订单额', '已回款', '未回款', '最近回款日'],
        'table_rows': table_rows,
        'export_rows': table_rows,
        'footnote': '应收=筛选期内销售订单总额；已回款=筛选期内 sales_payments 合计；客户维度未回款为近似值。',
    }


def _purchase_spend(db, filters):
    po_date_col = purchase_date_column(db)
    po_p, po_par = _purchase_filters(filters, 'po', po_date_col)
    po_w, po_params = _where(po_p, po_par)

    summary = db.execute(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount),0) as amt
        FROM purchase_orders po {po_w}
    """, po_params).fetchone()

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', po.{po_date_col}) as month,
            COALESCE(SUM(po.total_amount),0) as amt
        FROM purchase_orders po {po_w}
        GROUP BY month ORDER BY month
    """, po_params).fetchall()

    by_supplier = db.execute(f"""
        SELECT po.supplier as name, COALESCE(SUM(po.total_amount),0) as amt, COUNT(*) as cnt
        FROM purchase_orders po {po_w}
        GROUP BY po.supplier ORDER BY amt DESC LIMIT 10
    """, po_params).fetchall()

    table_rows = [
        {
            '供应商': r['name'] or '-',
            '采购单数': r['cnt'],
            '采购金额': f'{float(r["amt"]):.2f}',
        }
        for r in by_supplier
    ]

    return {
        'kpis': [
            {'label': '采购单数', 'value': str(summary['cnt']), 'border': 'primary'},
            {'label': '采购总额', 'value': f'{float(summary["amt"]):.2f}', 'border': 'danger'},
        ],
        'chart_data': {
            'monthly_labels': [r['month'] for r in monthly if r['month']],
            'monthly_amount': [float(r['amt']) for r in monthly if r['month']],
            'supplier_labels': [(r['name'] or '未知')[:10] for r in by_supplier],
            'supplier_amount': [float(r['amt']) for r in by_supplier],
        },
        'chart_mode': 'purchase_spend',
        'table_columns': ['供应商', '采购单数', '采购金额'],
        'table_rows': table_rows,
        'export_rows': table_rows,
    }


def _transport_freight(db, filters):
    parts, params = [], []
    if filters.get('date_from'):
        parts.append('tr.transport_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append('tr.transport_date<=?')
        params.append(filters['date_to'])
    if filters.get('project_id'):
        parts.append('po.project_id=?')
        params.append(filters['project_id'])
    tr_w, tr_params = _where(parts, params)
    join_po = 'LEFT JOIN purchase_orders po ON tr.purchase_id = po.id'

    summary = db.execute(f"""
        SELECT COUNT(*) as trips,
            COALESCE(SUM(tr.freight_amount),0) as freight,
            COALESCE(SUM(tr.quantity),0) as qty
        FROM transport_records tr {join_po} {tr_w}
    """, tr_params).fetchone()

    freight = float(summary['freight'] or 0)
    qty = float(summary['qty'] or 0)
    unit_avg = (freight / qty) if qty > 0 else 0

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', tr.transport_date) as month,
            COALESCE(SUM(tr.freight_amount),0) as freight,
            COUNT(*) as trips
        FROM transport_records tr {join_po} {tr_w}
        GROUP BY month ORDER BY month
    """, tr_params).fetchall()

    by_project = db.execute(f"""
        SELECT p.name, COALESCE(SUM(tr.freight_amount),0) as freight, COUNT(*) as trips
        FROM transport_records tr
        {join_po}
        LEFT JOIN projects p ON po.project_id = p.id
        {tr_w}
        GROUP BY po.project_id ORDER BY freight DESC LIMIT 10
    """, tr_params).fetchall()

    details = db.execute(f"""
        SELECT tr.batch_no, p.name as project_name, tr.transport_date,
            tr.quantity, tr.freight_amount, tr.vehicle_no
        FROM transport_records tr
        {join_po}
        LEFT JOIN projects p ON po.project_id = p.id
        {tr_w}
        ORDER BY tr.transport_date DESC LIMIT 50
    """, tr_params).fetchall()

    table_rows = [
        {
            '批次号': r['batch_no'] or '-',
            '项目': r['project_name'] or '-',
            '运输日期': r['transport_date'] or '-',
            '吨数': f'{float(r["quantity"] or 0):.2f}',
            '运费': f'{float(r["freight_amount"] or 0):.2f}',
            '车牌': r['vehicle_no'] or '-',
        }
        for r in details
    ]

    return {
        'kpis': [
            {'label': '车次', 'value': str(summary['trips']), 'border': 'primary'},
            {'label': '运费合计', 'value': f'{freight:.2f}', 'border': 'danger'},
            {'label': '运输吨数', 'value': f'{qty:.2f}', 'border': 'info'},
            {'label': '吨运费均价', 'value': f'{unit_avg:.2f}', 'border': 'warning'},
        ],
        'chart_data': {
            'monthly_labels': [r['month'] for r in monthly if r['month']],
            'monthly_freight': [float(r['freight']) for r in monthly if r['month']],
            'project_labels': [(r['name'] or '未指定')[:10] for r in by_project],
            'project_freight': [float(r['freight']) for r in by_project],
        },
        'chart_mode': 'transport_freight',
        'table_columns': ['批次号', '项目', '运输日期', '吨数', '运费', '车牌'],
        'table_rows': table_rows,
        'export_rows': table_rows,
    }


def _contract_funnel(db, filters):
    cp, par = _contract_filters(filters, 'c')
    w, p = _where(cp, par)
    contracts = db.execute(f"""
        SELECT c.id, c.contract_no, c.contract_name, c.contract_type, c.party,
            c.amount, c.status, p.name as project_name,
            COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=c.id), 0) as invoiced,
            COALESCE((SELECT SUM(sp.amount) FROM sales_payments sp WHERE sp.contract_id=c.id), 0) as sales_paid,
            COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.contract_id=c.id), 0) as other_paid
        FROM contracts c
        LEFT JOIN projects p ON c.project_id = p.id
        {w}
        ORDER BY c.amount DESC
    """, p).fetchall()

    total_contract = total_invoiced = total_paid = 0
    table_rows = []
    for r in contracts:
        amt = float(r['amount'] or 0)
        inv = float(r['invoiced'] or 0)
        paid = float(r['sales_paid'] or 0) + float(r['other_paid'] or 0)
        total_contract += amt
        total_invoiced += inv
        total_paid += paid
        inv_pct = (inv / amt * 100) if amt > 0 else 0
        pay_pct = (paid / amt * 100) if amt > 0 else 0
        table_rows.append({
            '合同号': r['contract_no'] or '-',
            '合同名称': r['contract_name'] or '-',
            '类型': r['contract_type'] or '-',
            '对方': r['party'] or '-',
            '项目': r['project_name'] or '-',
            '合同金额': f'{amt:.2f}',
            '已开票': f'{inv:.2f}',
            '已收付': f'{paid:.2f}',
            '开票率%': f'{inv_pct:.1f}',
            '执行率%': f'{pay_pct:.1f}',
            '状态': r['status'] or '-',
            '_contract_id': r['id'],
        })

    return {
        'kpis': [
            {'label': '合同数', 'value': str(len(table_rows)), 'border': 'primary'},
            {'label': '合同总额', 'value': f'{total_contract:.2f}', 'border': 'info'},
            {'label': '已开票', 'value': f'{total_invoiced:.2f}', 'border': 'success'},
            {'label': '已收付', 'value': f'{total_paid:.2f}', 'border': 'warning'},
        ],
        'chart_data': {
            'funnel_labels': ['合同金额', '已开票', '已收付'],
            'funnel_values': [total_contract, total_invoiced, total_paid],
        },
        'chart_mode': 'contract_funnel',
        'table_columns': ['合同号', '合同名称', '类型', '对方', '项目', '合同金额', '已开票', '已收付', '开票率%', '执行率%', '状态'],
        'table_rows': table_rows,
        'export_rows': [{k: v for k, v in row.items() if not k.startswith('_')} for row in table_rows],
        'footnote': '已收付=销售回款(sales_payments)+付款(payments)按合同归集；与费用流水口径不同。',
        'contract_links': True,
    }


def _invoice_summary(db, filters):
    ip, par = _invoice_filters(filters, 'i')
    w, p = _where(ip, par)

    summary = db.execute(f"""
        SELECT
            COALESCE(SUM(CASE WHEN i.invoice_type LIKE '%销%' OR i.invoice_type IN ('output', '销项') THEN i.amount ELSE 0 END), 0) as output_amt,
            COALESCE(SUM(CASE WHEN i.invoice_type LIKE '%进%' OR i.invoice_type IN ('input', '进项') THEN i.amount ELSE 0 END), 0) as input_amt,
            COALESCE(SUM(i.tax_amount), 0) as tax_total,
            COUNT(*) as cnt
        FROM invoices i {w}
    """, p).fetchone()

    by_type = db.execute(f"""
        SELECT COALESCE(i.invoice_type, '未分类') as typ,
            COUNT(*) as cnt, COALESCE(SUM(i.amount),0) as amt,
            COALESCE(SUM(i.tax_amount),0) as tax
        FROM invoices i {w}
        GROUP BY i.invoice_type ORDER BY amt DESC
    """, p).fetchall()

    monthly = db.execute(f"""
        SELECT strftime('%Y-%m', COALESCE(i.invoice_date, i.created_at)) as month,
            COALESCE(SUM(CASE WHEN i.invoice_type LIKE '%销%' OR i.invoice_type IN ('output', '销项') THEN i.amount ELSE 0 END), 0) as output_amt,
            COALESCE(SUM(CASE WHEN i.invoice_type LIKE '%进%' OR i.invoice_type IN ('input', '进项') THEN i.amount ELSE 0 END), 0) as input_amt
        FROM invoices i {w}
        GROUP BY month ORDER BY month
    """, p).fetchall()

    table_rows = [
        {
            '发票类型': r['typ'],
            '张数': r['cnt'],
            '金额': f'{float(r["amt"]):.2f}',
            '税额': f'{float(r["tax"]):.2f}',
        }
        for r in by_type
    ]

    months = [r['month'] for r in monthly if r['month']]
    return {
        'kpis': [
            {'label': '发票张数', 'value': str(summary['cnt']), 'border': 'primary'},
            {'label': '销项金额', 'value': f'{float(summary["output_amt"]):.2f}', 'border': 'success'},
            {'label': '进项金额', 'value': f'{float(summary["input_amt"]):.2f}', 'border': 'danger'},
            {'label': '税额合计', 'value': f'{float(summary["tax_total"]):.2f}', 'border': 'warning'},
        ],
        'chart_data': {
            'monthly_labels': months,
            'monthly_output': [float(r['output_amt']) for r in monthly if r['month']],
            'monthly_input': [float(r['input_amt']) for r in monthly if r['month']],
            'type_labels': [r['typ'][:12] for r in by_type],
            'type_amount': [float(r['amt']) for r in by_type],
        },
        'chart_mode': 'invoice_summary',
        'table_columns': ['发票类型', '张数', '金额', '税额'],
        'table_rows': table_rows,
        'export_rows': table_rows,
    }


def _invest_where(filters, pid, date_col):
    parts, params = [], []
    if pid:
        parts.append('project_id=?')
        params.append(pid)
    if filters.get('date_from'):
        parts.append(f'{date_col}>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'{date_col}<=?')
        params.append(filters['date_to'])
    if parts:
        return 'WHERE ' + ' AND '.join(parts), params
    return '', []


def _investment_dividend(db, filters):
    pid = filters.get('project_id')
    inv_where, inv_params = _invest_where(filters, pid, 'invest_date')
    div_where, div_params = _invest_where(filters, pid, 'dividend_date')
    inv_and, _ = _invest_where(filters, pid, 'invest_date')
    inv_and = inv_and.replace('WHERE ', ' AND ') if inv_and else ''
    div_and, _ = _invest_where(filters, pid, 'dividend_date')
    div_and = div_and.replace('WHERE ', ' AND ') if div_and else ''

    total_inv = float(db.execute(
        f'SELECT COALESCE(SUM(amount),0) FROM investments {inv_where}',
        inv_params,
    ).fetchone()[0] or 0)
    total_div = float(db.execute(
        f'SELECT COALESCE(SUM(amount),0) FROM dividends {div_where}',
        div_params,
    ).fetchone()[0] or 0)
    roi = (total_div / total_inv * 100) if total_inv > 0 else 0

    rows = db.execute(f"""
        SELECT pt.name,
            COALESCE((SELECT SUM(i.amount) FROM investments i
                WHERE i.participant_id=pt.id{inv_and}), 0) as invested,
            COALESCE((SELECT SUM(d.amount) FROM dividends d
                WHERE d.participant_id=pt.id{div_and}), 0) as dividend
        FROM participants pt
        ORDER BY invested DESC
    """, inv_params + div_params).fetchall()
    rows = [r for r in rows if float(r['invested'] or 0) > 0 or float(r['dividend'] or 0) > 0]

    table_rows = []
    chart_labels, chart_inv, chart_div = [], [], []
    for r in rows:
        inv = float(r['invested'] or 0)
        div = float(r['dividend'] or 0)
        table_rows.append({
            '参与人': r['name'] or '-',
            '出资': f'{inv:.2f}',
            '分红': f'{div:.2f}',
            '回报倍率': f'{(div / inv):.2f}' if inv > 0 else '-',
        })
        if len(chart_labels) < 12:
            chart_labels.append((r['name'] or '-')[:8])
            chart_inv.append(inv)
            chart_div.append(div)

    project_rows = []
    if not pid:
        for pr in db.execute('SELECT id, name FROM projects ORDER BY name').fetchall():
            iw, ip = _invest_where(filters, str(pr['id']), 'invest_date')
            dw, dp = _invest_where(filters, str(pr['id']), 'dividend_date')
            inv = float(db.execute(
                f'SELECT COALESCE(SUM(amount),0) FROM investments {iw}', ip,
            ).fetchone()[0] or 0)
            div = float(db.execute(
                f'SELECT COALESCE(SUM(amount),0) FROM dividends {dw}', dp,
            ).fetchone()[0] or 0)
            if inv > 0 or div > 0:
                project_rows.append({
                    '项目': pr['name'],
                    '出资': f'{inv:.2f}',
                    '分红': f'{div:.2f}',
                })

    return {
        'kpis': [
            {'label': '出资合计', 'value': f'{total_inv:.2f}', 'border': 'primary'},
            {'label': '分红合计', 'value': f'{total_div:.2f}', 'border': 'success'},
            {'label': '分红/出资', 'value': f'{roi:.1f}%', 'border': 'info'},
            {'label': '参与人数', 'value': str(len(table_rows)), 'border': 'warning'},
        ],
        'chart_data': {
            'participant_labels': chart_labels,
            'invest_data': chart_inv,
            'dividend_data': chart_div,
        },
        'chart_mode': 'investment_dividend',
        'table_columns': ['参与人', '出资', '分红', '回报倍率'],
        'table_rows': table_rows,
        'export_rows': table_rows,
        'project_rows': project_rows,
        'project_table_columns': ['项目', '出资', '分红'],
    }


def _reconciliation_summary(db, filters):
    parts, params = [], []
    if filters.get('project_id'):
        parts.append('po.project_id=?')
        params.append(filters['project_id'])
    if filters.get('date_from'):
        parts.append('COALESCE(r.reconciliation_date, r.created_at)>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append('COALESCE(r.reconciliation_date, r.created_at)<=?')
        params.append(filters['date_to'] + ' 23:59:59')
    w, p = _where(parts, params)

    summary = db.execute(f"""
        SELECT COUNT(*) as cnt,
            COALESCE(SUM(ABS(r.qty_diff)), 0) as qty_diff_sum,
            COALESCE(SUM(ABS(r.freight_diff)), 0) as freight_diff_sum,
            SUM(CASE WHEN r.status IN ('待对账', 'pending', 'draft') THEN 1 ELSE 0 END) as pending_cnt
        FROM reconciliations r
        LEFT JOIN purchase_orders po ON r.purchase_id = po.id
        {w}
    """, p).fetchone()

    rows = db.execute(f"""
        SELECT r.reconciliation_no, r.reconciliation_date, r.status,
            r.purchase_quantity, r.total_transport_qty, r.qty_diff, r.qty_diff_rate,
            r.total_freight, r.total_invoice_amount, r.freight_diff,
            po.purchase_no, po.supplier, p.name as project_name
        FROM reconciliations r
        LEFT JOIN purchase_orders po ON r.purchase_id = po.id
        LEFT JOIN projects p ON po.project_id = p.id
        {w}
        ORDER BY r.reconciliation_date DESC LIMIT 100
    """, p).fetchall()

    table_rows = [
        {
            '对账单号': r['reconciliation_no'] or '-',
            '采购单号': r['purchase_no'] or '-',
            '项目': r['project_name'] or '-',
            '供应商': r['supplier'] or '-',
            '对账日期': r['reconciliation_date'] or '-',
            '采购吨数': f'{float(r["purchase_quantity"] or 0):.2f}',
            '运输吨数': f'{float(r["total_transport_qty"] or 0):.2f}',
            '吨差': f'{float(r["qty_diff"] or 0):.2f}',
            '吨差率%': f'{float(r["qty_diff_rate"] or 0):.2f}',
            '运费': f'{float(r["total_freight"] or 0):.2f}',
            '发票额': f'{float(r["total_invoice_amount"] or 0):.2f}',
            '运费差': f'{float(r["freight_diff"] or 0):.2f}',
            '状态': r['status'] or '-',
        }
        for r in rows
    ]

    status_counts = {}
    for r in rows:
        st = r['status'] or '未知'
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        'kpis': [
            {'label': '对账单数', 'value': str(summary['cnt']), 'border': 'primary'},
            {'label': '待对账', 'value': str(summary['pending_cnt']), 'border': 'warning'},
            {'label': '吨差绝对值合计', 'value': f'{float(summary["qty_diff_sum"]):.2f}', 'border': 'danger'},
            {'label': '运费差绝对值合计', 'value': f'{float(summary["freight_diff_sum"]):.2f}', 'border': 'info'},
        ],
        'chart_data': {
            'status_labels': list(status_counts.keys()),
            'status_values': list(status_counts.values()),
        },
        'chart_mode': 'reconciliation_summary',
        'table_columns': list(table_rows[0].keys()) if table_rows else [
            '对账单号', '采购单号', '项目', '供应商', '对账日期', '吨差', '运费差', '状态'
        ],
        'table_rows': table_rows,
        'export_rows': table_rows,
    }


def _client_collab_funds(db, filters):
    from client_collab_scope import (
        apply_client_id_scope_sql,
        list_company_summaries_scoped,
    )

    user_id = filters.get('_scope_user_id')
    role = filters.get('_scope_role', '')
    companies = list_company_summaries_scoped(db, user_id, role)
    date_from = filters.get('date_from')
    date_to = filters.get('date_to')

    period_recharge = period_deduct = 0.0
    monthly = {}

    recharge_where = ["cr.status IN ('confirmed', 'approved', 'active')"]
    deduct_where = []
    r_params, d_params = [], []

    cr_scope, cr_scope_p = apply_client_id_scope_sql(db, user_id, role, 'cr')
    if cr_scope:
        recharge_where.append(cr_scope.replace(' AND ', '', 1))
        r_params.extend(cr_scope_p)
    cd_scope, cd_scope_p = apply_client_id_scope_sql(db, user_id, role, 'cd')
    if cd_scope:
        deduct_where.append(cd_scope.replace(' AND ', '', 1))
        d_params.extend(cd_scope_p)
    if not deduct_where:
        deduct_where = ['1=1']

    if date_from:
        recharge_where.append('date(COALESCE(cr.confirmed_at, cr.created_at))>=?')
        deduct_where.append('date(COALESCE(cd.deduct_date, cd.created_at))>=?')
        r_params.append(date_from)
        d_params.append(date_from)
    if date_to:
        recharge_where.append('date(COALESCE(cr.confirmed_at, cr.created_at))<=?')
        deduct_where.append('date(COALESCE(cd.deduct_date, cd.created_at))<=?')
        r_params.append(date_to)
        d_params.append(date_to)

    rw = ' AND '.join(recharge_where)
    period_recharge = float(db.execute(f"""
        SELECT COALESCE(SUM(cr.amount),0) FROM client_recharges cr WHERE {rw}
    """, r_params).fetchone()[0] or 0)

    dw = ' AND '.join(deduct_where)
    period_deduct = float(db.execute(f"""
        SELECT COALESCE(SUM(cd.amount),0) FROM client_deductions cd WHERE {dw}
    """, d_params).fetchone()[0] or 0)

    monthly_rows = db.execute(f"""
        SELECT strftime('%Y-%m', date(COALESCE(cr.confirmed_at, cr.created_at))) as month,
            COALESCE(SUM(cr.amount),0) as recharge
        FROM client_recharges cr WHERE {rw}
        GROUP BY month
    """, r_params).fetchall()
    for mr in monthly_rows:
        if mr['month']:
            monthly[mr['month']] = {'recharge': float(mr['recharge'] or 0), 'deduct': 0}

    monthly_d = db.execute(f"""
        SELECT strftime('%Y-%m', date(COALESCE(cd.deduct_date, cd.created_at))) as month,
            COALESCE(SUM(cd.amount),0) as deduct
        FROM client_deductions cd WHERE {dw}
        GROUP BY month
    """, d_params).fetchall()
    for mr in monthly_d:
        if mr['month']:
            monthly.setdefault(mr['month'], {'recharge': 0, 'deduct': 0})
            monthly[mr['month']]['deduct'] = float(mr['deduct'] or 0)

    months = sorted(monthly.keys())
    total_balance = sum(float(c.get('balance') or 0) for c in companies)

    table_rows = []
    for c in companies:
        table_rows.append({
            '公司': c.get('company_name') or '-',
            '账户数': c.get('account_count', 0),
            '当前余额': f'{float(c.get("balance") or 0):.2f}',
            '累计充值': f'{float(c.get("total_recharge") or 0):.2f}',
            '累计扣减': f'{float(c.get("total_deduct") or 0):.2f}',
            '待确认充值': f'{float(c.get("pending_recharge") or 0):.2f}',
            '_customer_id': c.get('customer_id') or 0,
            '_link_id': c.get('primary_client_id'),
        })

    return {
        'kpis': [
            {'label': '公司数', 'value': str(len(companies)), 'border': 'primary'},
            {'label': '当前余额合计', 'value': f'{total_balance:.2f}', 'border': 'success'},
            {'label': '期间充值', 'value': f'{period_recharge:.2f}', 'border': 'info'},
            {'label': '期间扣减', 'value': f'{period_deduct:.2f}', 'border': 'danger'},
        ],
        'chart_data': {
            'monthly_labels': months,
            'monthly_recharge': [monthly[m]['recharge'] for m in months],
            'monthly_deduct': [monthly[m]['deduct'] for m in months],
        },
        'chart_mode': 'client_collab_funds',
        'table_columns': ['公司', '账户数', '当前余额', '累计充值', '累计扣减', '待确认充值'],
        'table_rows': table_rows,
        'export_rows': [{k: v for k, v in r.items() if not k.startswith('_')} for r in table_rows],
        'client_links': role in ('admin', 'finance', 'client_collab'),
        'footnote': '仅统计您有权限查看的协同客户；管理员/财务可见全部，协同专员仅负责客户。',
    }


def chart_data_json(data):
    return json.dumps(data, ensure_ascii=False)
