# -*- coding: utf-8 -*-
"""客户协同独立报表（仅 client_recharges / client_deductions，与 ERP 其它模块数据隔离）"""
from collections import defaultdict
from datetime import datetime, timedelta

from client_portal_utils import (
    company_scope_client_ids,
    compute_balance_totals,
    deduct_type_label,
    get_client_by_id,
    is_low_balance,
    LOW_BALANCE_THRESHOLD,
)
from client_collab_ops import primary_client_for_company

REPORT_CATALOG = (
    {
        'slug': 'overview',
        'title': '资金概览',
        'description': '充值、扣减、剩余余额及预警一览',
        'icon': 'bi-wallet2',
    },
    {
        'slug': 'trend',
        'title': '收支趋势',
        'description': '按日/月查看充值与扣减对比',
        'icon': 'bi-bar-chart-line',
    },
    {
        'slug': 'balance',
        'title': '余额走势',
        'description': '剩余余额随时间变化曲线',
        'icon': 'bi-graph-up-arrow',
    },
    {
        'slug': 'deduction',
        'title': '扣减分析',
        'description': '按类型、品项汇总扣减构成',
        'icon': 'bi-pie-chart',
    },
    {
        'slug': 'recharge',
        'title': '充值分析',
        'description': '按支付方式与审核状态统计充值',
        'icon': 'bi-cash-stack',
    },
)

REPORT_SLUGS = frozenset(r['slug'] for r in REPORT_CATALOG)


def get_report_meta(slug):
    for r in REPORT_CATALOG:
        if r['slug'] == slug:
            return r
    return None


def default_date_range(days=90):
    end = datetime.now().date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def resolve_client_for_report(db, customer_id=None, client_id=None):
    if customer_id:
        return primary_client_for_company(db, int(customer_id))
    if client_id:
        return get_client_by_id(db, int(client_id))
    return None


def _scope_ids(db, client):
    return company_scope_client_ids(db, client)


def _date_only(value):
    if not value:
        return ''
    return str(value)[:10]


def _in_range(date_str, start_date, end_date):
    d = _date_only(date_str)
    if not d:
        return False
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


def _period_key(date_str, granularity):
    d = _date_only(date_str)
    if not d:
        return ''
    if granularity == 'month':
        return d[:7]
    return d


def _fetch_recharges(db, scope_ids, start_date='', end_date='', confirmed_only=True):
    if not scope_ids:
        return []
    ph = ','.join('?' * len(scope_ids))
    status_sql = " AND status='confirmed'" if confirmed_only else ''
    rows = db.execute(
        f"""SELECT id, amount, payment_method, status, created_at, remark
            FROM client_recharges
            WHERE client_id IN ({ph}){status_sql}
            ORDER BY created_at, id""",
        scope_ids,
    ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        if _in_range(row.get('created_at'), start_date, end_date):
            out.append(row)
    return out


def _fetch_deductions(db, scope_ids, start_date='', end_date=''):
    if not scope_ids:
        return []
    ph = ','.join('?' * len(scope_ids))
    rows = db.execute(
        f"""SELECT id, amount, quantity, item_name, remark,
                   COALESCE(deduct_date, created_at) AS tx_date,
                   COALESCE(deduct_type, 'outbound') AS deduct_type
            FROM client_deductions
            WHERE client_id IN ({ph})
            ORDER BY COALESCE(deduct_date, created_at), id""",
        scope_ids,
    ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        if _in_range(row.get('tx_date'), start_date, end_date):
            out.append(row)
    return out


def _sum_amount(rows, key='amount'):
    return sum(float(r.get(key) or 0) for r in rows)


def build_overview_report(db, client, start_date='', end_date=''):
    scope_ids = _scope_ids(db, client)
    balance, total_recharge, total_deduct = compute_balance_totals(db, client)
    recharges = _fetch_recharges(db, scope_ids, start_date, end_date)
    deductions = _fetch_deductions(db, scope_ids, start_date, end_date)
    period_recharge = _sum_amount(recharges)
    period_deduct = _sum_amount(deductions)

    pending_recharge = 0.0
    if scope_ids:
        ph = ','.join('?' * len(scope_ids))
        pending_recharge = float(db.execute(
            f"""SELECT COALESCE(SUM(amount), 0) FROM client_recharges
                WHERE client_id IN ({ph}) AND status='pending'""",
            scope_ids,
        ).fetchone()[0] or 0)

    mini_trend = build_trend_report(db, client, start_date, end_date, 'day')
    return {
        'balance': balance,
        'total_recharge': total_recharge,
        'total_deduct': total_deduct,
        'period_recharge': period_recharge,
        'period_deduct': period_deduct,
        'period_net': period_recharge - period_deduct,
        'pending_recharge': pending_recharge,
        'low_balance': is_low_balance(balance),
        'threshold': LOW_BALANCE_THRESHOLD,
        'mini_trend': mini_trend,
    }


def build_trend_report(db, client, start_date='', end_date='', granularity='day'):
    scope_ids = _scope_ids(db, client)
    recharges = _fetch_recharges(db, scope_ids, start_date, end_date)
    deductions = _fetch_deductions(db, scope_ids, start_date, end_date)

    bucket = defaultdict(lambda: {'recharge': 0.0, 'deduction': 0.0})
    for r in recharges:
        k = _period_key(r.get('created_at'), granularity)
        if k:
            bucket[k]['recharge'] += float(r.get('amount') or 0)
    for d in deductions:
        k = _period_key(d.get('tx_date'), granularity)
        if k:
            bucket[k]['deduction'] += float(d.get('amount') or 0)

    labels = sorted(bucket.keys())
    series = []
    for k in labels:
        rec = bucket[k]['recharge']
        ded = bucket[k]['deduction']
        series.append({
            'period': k,
            'recharge': round(rec, 2),
            'deduction': round(ded, 2),
            'net': round(rec - ded, 2),
        })

    return {
        'granularity': granularity,
        'labels': labels,
        'recharge': [bucket[k]['recharge'] for k in labels],
        'deduction': [bucket[k]['deduction'] for k in labels],
        'net': [bucket[k]['recharge'] - bucket[k]['deduction'] for k in labels],
        'rows': series,
        'total_recharge': round(_sum_amount(recharges), 2),
        'total_deduction': round(_sum_amount(deductions), 2),
    }


def build_balance_report(db, client, start_date='', end_date=''):
    scope_ids = _scope_ids(db, client)
    balance, total_recharge, total_deduct = compute_balance_totals(db, client)

    events = []
    if scope_ids:
        ph = ','.join('?' * len(scope_ids))
        for r in db.execute(
            f"""SELECT created_at AS tx_date, amount, 'recharge' AS kind
                FROM client_recharges
                WHERE client_id IN ({ph}) AND status='confirmed'
                ORDER BY created_at, id""",
            scope_ids,
        ).fetchall():
            events.append(dict(r))
        for r in db.execute(
            f"""SELECT COALESCE(deduct_date, created_at) AS tx_date, amount, 'deduction' AS kind
                FROM client_deductions
                WHERE client_id IN ({ph})
                ORDER BY COALESCE(deduct_date, created_at), id""",
            scope_ids,
        ).fetchall():
            events.append(dict(r))

    events.sort(key=lambda x: (_date_only(x.get('tx_date')), x.get('kind') or ''))

    running = 0.0
    daily_balance = {}
    for ev in events:
        amt = float(ev.get('amount') or 0)
        if ev['kind'] == 'recharge':
            running += amt
        else:
            running -= amt
        day = _date_only(ev.get('tx_date'))
        if day:
            daily_balance[day] = running

    if start_date or end_date:
        filtered = {
            d: v for d, v in daily_balance.items()
            if _in_range(d, start_date, end_date)
        }
    else:
        filtered = daily_balance

    labels = sorted(filtered.keys())
    values = [round(filtered[d], 2) for d in labels]

    return {
        'labels': labels,
        'values': values,
        'current_balance': round(balance, 2),
        'total_recharge': round(total_recharge, 2),
        'total_deduct': round(total_deduct, 2),
        'low_balance': is_low_balance(balance),
        'threshold': LOW_BALANCE_THRESHOLD,
    }


def build_deduction_report(db, client, start_date='', end_date=''):
    scope_ids = _scope_ids(db, client)
    deductions = _fetch_deductions(db, scope_ids, start_date, end_date)

    by_type = defaultdict(float)
    by_item = defaultdict(lambda: {'amount': 0.0, 'qty': 0.0, 'count': 0})
    for d in deductions:
        dtype = d.get('deduct_type') or 'outbound'
        by_type[dtype] += float(d.get('amount') or 0)
        name = (d.get('item_name') or d.get('remark') or '未命名').strip() or '未命名'
        by_item[name]['amount'] += float(d.get('amount') or 0)
        by_item[name]['qty'] += float(d.get('quantity') or 0)
        by_item[name]['count'] += 1

    type_rows = [
        {
            'type': k,
            'label': deduct_type_label(k),
            'amount': round(v, 2),
        }
        for k, v in sorted(by_type.items(), key=lambda x: -x[1])
    ]
    item_rows = [
        {
            'name': name,
            'amount': round(data['amount'], 2),
            'qty': round(data['qty'], 2),
            'count': data['count'],
        }
        for name, data in sorted(by_item.items(), key=lambda x: -x[1]['amount'])[:15]
    ]

    return {
        'total': round(_sum_amount(deductions), 2),
        'count': len(deductions),
        'by_type': type_rows,
        'type_labels': [r['label'] for r in type_rows],
        'type_amounts': [r['amount'] for r in type_rows],
        'top_items': item_rows,
    }


def build_recharge_report(db, client, start_date='', end_date=''):
    scope_ids = _scope_ids(db, client)
    recharges = _fetch_recharges(db, scope_ids, start_date, end_date, confirmed_only=False)

    by_method = defaultdict(float)
    by_status = defaultdict(float)
    for r in recharges:
        method = (r.get('payment_method') or '其它').strip() or '其它'
        by_method[method] += float(r.get('amount') or 0)
        by_status[r.get('status') or 'pending'] += float(r.get('amount') or 0)

    method_rows = [
        {'method': k, 'amount': round(v, 2)}
        for k, v in sorted(by_method.items(), key=lambda x: -x[1])
    ]
    status_labels = {
        'confirmed': '已确认',
        'pending': '待确认',
        'rejected': '已拒绝',
    }
    status_rows = [
        {
            'status': k,
            'label': status_labels.get(k, k),
            'amount': round(v, 2),
        }
        for k, v in sorted(by_status.items(), key=lambda x: -x[1])
    ]

    balance, total_recharge, _ = compute_balance_totals(db, client)
    return {
        'total_confirmed': round(total_recharge, 2),
        'period_total': round(_sum_amount(recharges), 2),
        'count': len(recharges),
        'by_method': method_rows,
        'method_labels': [r['method'] for r in method_rows],
        'method_amounts': [r['amount'] for r in method_rows],
        'by_status': status_rows,
        'balance': round(balance, 2),
    }


def build_report_payload(db, slug, client, start_date='', end_date='', granularity='day'):
    if slug == 'overview':
        return build_overview_report(db, client, start_date, end_date)
    if slug == 'trend':
        return build_trend_report(db, client, start_date, end_date, granularity)
    if slug == 'balance':
        return build_balance_report(db, client, start_date, end_date)
    if slug == 'deduction':
        return build_deduction_report(db, client, start_date, end_date)
    if slug == 'recharge':
        return build_recharge_report(db, client, start_date, end_date)
    return None
