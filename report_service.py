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


def parse_filters(request):
    today = date.today()
    year_start = date(today.year, 1, 1)
    date_from = (request.args.get('date_from') or '').strip() or year_start.isoformat()
    date_to = (request.args.get('date_to') or '').strip() or today.isoformat()
    project_id = (request.args.get('project_id') or '').strip()
    customer_name = (request.args.get('customer_name') or '').strip()
    supplier = (request.args.get('supplier') or '').strip()
    return {
        'date_from': date_from,
        'date_to': date_to,
        'project_id': project_id,
        'customer_name': customer_name,
        'supplier': supplier,
    }


def _where(parts, params):
    if not parts:
        return '', params
    return ' WHERE ' + ' AND '.join(parts), params


def _trans_filters(filters, alias='t'):
    parts, params = [], []
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


def _purchase_filters(filters, alias='po', date_col='order_date'):
    parts, params = [], []
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


def load_projects(db):
    return db.execute('SELECT id, name FROM projects ORDER BY name').fetchall()


def _contract_filters(filters, alias='c'):
    parts, params = [], []
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
