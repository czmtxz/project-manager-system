# -*- coding: utf-8 -*-
"""客户协同经营：按公司充值、出库扣减、导入与汇总"""
import os
import re
import uuid
from datetime import datetime

from client_portal_utils import (
    resolve_or_create_customer,
    build_portal_transactions,
    company_scope_client_ids,
)

PAYMENT_METHODS = {
    'bank_transfer': '银行转账',
    'alipay': '支付宝',
    'wechat': '微信支付',
    'cash': '现金',
    'other': '其他',
}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _month_key(dt_str):
    if not dt_str:
        return '未知'
    s = str(dt_str).strip()
    return s[:7] if len(s) >= 7 else s


def summarize_recharge_records(recharges):
    """充值记录汇总：按付款方式、月份"""
    total_amount = 0.0
    by_method = {}
    by_month = {}
    for row in recharges:
        r = dict(row)
        amt = float(r.get('amount') or 0)
        total_amount += amt
        method = r.get('payment_method') or 'other'
        bucket = by_method.setdefault(method, {'count': 0, 'amount': 0.0})
        bucket['count'] += 1
        bucket['amount'] += amt
        mk = _month_key(r.get('created_at'))
        mb = by_month.setdefault(mk, {'count': 0, 'amount': 0.0})
        mb['count'] += 1
        mb['amount'] += amt
    return {
        'total_count': len(recharges),
        'total_amount': total_amount,
        'by_method': sorted(
            [{'method': k, 'label': PAYMENT_METHODS.get(k, k), **v} for k, v in by_method.items()],
            key=lambda x: -x['amount'],
        ),
        'by_month': sorted(
            [{'month': k, **v} for k, v in by_month.items()],
            key=lambda x: x['month'],
            reverse=True,
        ),
    }


def _date_key(dt_str):
    if not dt_str:
        return '未知'
    s = str(dt_str).strip()
    return s[:10] if len(s) >= 10 else s


DEDUCTION_GROUP_FIELDS = {
    'date': '日期',
    'month': '月份',
    'item_name': '品名',
    'truck_count': '车数',
    'unit_price': '单价',
}


def deduction_rows_for_summary(deductions):
    """扣减明细（供前端按字段动态汇总）。"""
    rows = []
    for row in deductions:
        d = dict(row)
        dt = d.get('deduct_date') or d.get('created_at') or ''
        rows.append({
            'date': _date_key(dt),
            'month': _month_key(dt),
            'item_name': (d.get('item_name') or '').strip() or '未填写',
            'truck_count': float(d.get('truck_count') or 0),
            'unit_price': float(d.get('unit_price') or 0),
            'quantity': float(d.get('quantity') or 0),
            'amount': float(d.get('amount') or 0),
        })
    return rows


def summarize_deduction_records(deductions):
    """扣减记录合计。"""
    total_amount = 0.0
    total_qty = 0.0
    total_trucks = 0.0
    for row in deductions:
        d = dict(row)
        total_amount += float(d.get('amount') or 0)
        total_qty += float(d.get('quantity') or 0)
        total_trucks += float(d.get('truck_count') or 0)
    return {
        'total_count': len(deductions),
        'total_qty': total_qty,
        'total_trucks': total_trucks,
        'total_amount': total_amount,
    }


def primary_client_for_customer(db, customer_id):
    """取该公司下首个已激活门户账号。"""
    if not customer_id:
        return None
    row = db.execute(
        """SELECT * FROM client_accounts
           WHERE customer_id=? AND status IN ('approved', 'active')
           ORDER BY id LIMIT 1""",
        (customer_id,),
    ).fetchone()
    return dict(row) if row else None


def primary_client_for_company(db, customer_id=None, client_id=None):
    if customer_id:
        c = primary_client_for_customer(db, customer_id)
        if c:
            return c
    if client_id:
        row = db.execute(
            "SELECT * FROM client_accounts WHERE id=?", (client_id,)
        ).fetchone()
        return dict(row) if row else None
    return None


def list_company_summaries(db):
    """按公司聚合余额（customer_id 或独立 company_name）。"""
    rows = db.execute(
        """SELECT
               COALESCE(ca.customer_id, 0) AS customer_id,
               COALESCE(c.name, ca.company_name, '未命名') AS company_name,
               MIN(ca.id) AS primary_client_id,
               COUNT(*) AS account_count,
               COALESCE(SUM(ca.balance), 0) AS balance,
               COALESCE(SUM(ca.total_recharge), 0) AS total_recharge,
               COALESCE(SUM(ca.total_deduct), 0) AS total_deduct,
               SUM(CASE WHEN ca.status='pending' THEN 1 ELSE 0 END) AS pending_accounts
           FROM client_accounts ca
           LEFT JOIN customers c ON ca.customer_id = c.id
           GROUP BY COALESCE(ca.customer_id, 0), COALESCE(c.name, ca.company_name)
           ORDER BY company_name"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        pending_recharge = db.execute(
            """SELECT COALESCE(SUM(cr.amount), 0) FROM client_recharges cr
               JOIN client_accounts ca ON cr.client_id = ca.id
               WHERE cr.status='pending'
               AND (
                 (? > 0 AND ca.customer_id = ?)
                 OR (? = 0 AND ca.id = ?)
               )""",
            (d['customer_id'], d['customer_id'], d['customer_id'], d['primary_client_id']),
        ).fetchone()[0]
        d['pending_recharge'] = float(pending_recharge or 0)
        out.append(d)
    return out


def get_company_workspace(db, customer_id=0, client_id=None):
    client = primary_client_for_company(db, customer_id or None, client_id)
    if not client:
        return None
    cid = client.get('customer_id') or customer_id
    company_name = client.get('company_name') or ''
    if cid:
        crow = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        if crow:
            company_name = crow['name']
    bal, total_recharge, total_deduct = 0.0, 0.0, 0.0
    if cid:
        from client_portal_utils import aggregate_company_balance
        bal, total_recharge, total_deduct = aggregate_company_balance(db, client)
    else:
        bal = float(client.get('balance') or 0)
        total_recharge = float(client.get('total_recharge') or 0)
        total_deduct = float(client.get('total_deduct') or 0)

    transactions, _, _, _ = build_portal_transactions(db, client)
    scope_ids = company_scope_client_ids(db, client)
    ph = ','.join('?' * len(scope_ids))
    recharges = db.execute(
        f"""SELECT cr.*, ca.company_name FROM client_recharges cr
            JOIN client_accounts ca ON cr.client_id = ca.id
            WHERE cr.client_id IN ({ph}) ORDER BY cr.created_at DESC, cr.id DESC""",
        scope_ids,
    ).fetchall()
    deductions = db.execute(
        f"""SELECT cd.*, ca.company_name FROM client_deductions cd
            JOIN client_accounts ca ON cd.client_id = ca.id
            WHERE cd.client_id IN ({ph})
            ORDER BY COALESCE(cd.deduct_date, cd.created_at) DESC, cd.id DESC""",
        scope_ids,
    ).fetchall()
    accounts = db.execute(
        """SELECT id, username, company_name, status, balance
           FROM client_accounts
           WHERE customer_id=? OR id=?
           ORDER BY id""",
        (cid or -1, client['id']),
    ).fetchall() if cid else [client]

    pending_recharge = db.execute(
        f"""SELECT COALESCE(SUM(amount), 0) FROM client_recharges
            WHERE client_id IN ({ph}) AND status='pending'""",
        scope_ids,
    ).fetchone()[0]

    return {
        'client': client,
        'customer_id': cid or 0,
        'company_name': company_name,
        'balance': bal,
        'total_recharge': total_recharge,
        'total_deduct': total_deduct,
        'pending_recharge': float(pending_recharge or 0),
        'transactions': transactions[:80],
        'recharges': recharges,
        'deductions': deductions,
        'recharge_summary': summarize_recharge_records(recharges),
        'deduction_summary': summarize_deduction_records(deductions),
        'deduction_summary_rows': deduction_rows_for_summary(deductions),
        'deduction_group_fields': DEDUCTION_GROUP_FIELDS,
        'accounts': accounts,
        'payment_methods': PAYMENT_METHODS,
    }


def record_client_recharge(db, client_id, amount, payment_method, payment_no='',
                           remark='', attachment='', user_id=None, auto_confirm=True):
    amount = float(amount)
    if amount <= 0:
        raise ValueError('充值金额须大于 0')
    client = db.execute(
        "SELECT * FROM client_accounts WHERE id=?", (client_id,)
    ).fetchone()
    if not client:
        raise ValueError('客户账号不存在')
    if client['status'] not in ('approved', 'active'):
        raise ValueError('客户账号未激活，无法充值')

    now = _now()
    status = 'confirmed' if auto_confirm else 'pending'
    cur = db.execute(
        """INSERT INTO client_recharges
           (client_id, amount, payment_method, payment_no, remark, attachment,
            status, confirmed_by, confirmed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            client_id, amount, payment_method, payment_no, remark, attachment,
            status,
            user_id if auto_confirm else None,
            now if auto_confirm else None,
            now,
        ),
    )
    recharge_id = cur.lastrowid
    if auto_confirm:
        db.execute(
            """UPDATE client_accounts
               SET balance=balance+?, total_recharge=total_recharge+?, updated_at=?
               WHERE id=?""",
            (amount, amount, now, client_id),
        )
        db.execute(
            """INSERT INTO client_messages (client_id, title, content, msg_type)
               VALUES (?, '充值到账', ?, 'notice')""",
            (client_id, f'管理员已为您充值 {amount:.2f} 元，已到账。'),
        )
    return recharge_id


def confirm_client_recharge(db, recharge_id, user_id):
    r = db.execute("SELECT * FROM client_recharges WHERE id=?", (recharge_id,)).fetchone()
    if not r:
        raise ValueError('充值记录不存在')
    if r['status'] != 'pending':
        raise ValueError('不在待确认状态')
    now = _now()
    db.execute(
        "UPDATE client_recharges SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE id=?",
        (user_id, now, recharge_id),
    )
    db.execute(
        """UPDATE client_accounts SET balance=balance+?, total_recharge=total_recharge+?, updated_at=?
           WHERE id=?""",
        (r['amount'], r['amount'], now, r['client_id']),
    )
    db.execute(
        """INSERT INTO client_messages (client_id, title, content, msg_type)
           VALUES (?, '充值成功', ?, 'notice')""",
        (r['client_id'], f'您的充值申请 {r["amount"]:.2f} 元已确认到账。'),
    )
    return dict(r)


def unconfirm_client_recharge(db, recharge_id, user_id):
    r = db.execute("SELECT * FROM client_recharges WHERE id=?", (recharge_id,)).fetchone()
    if not r:
        raise ValueError('充值记录不存在')
    if r['status'] != 'confirmed':
        raise ValueError('只能反审核已确认的记录')
    now = _now()
    db.execute(
        """UPDATE client_accounts SET balance=balance-?, total_recharge=total_recharge-?, updated_at=?
           WHERE id=?""",
        (r['amount'], r['amount'], now, r['client_id']),
    )
    db.execute(
        "UPDATE client_recharges SET status='pending', confirmed_by=NULL, confirmed_at=NULL WHERE id=?",
        (recharge_id,),
    )
    db.execute(
        """INSERT INTO client_messages (client_id, title, content, msg_type)
           VALUES (?, '充值反审核', ?, 'notice')""",
        (r['client_id'], f'充值 {r["amount"]:.2f} 元已退回待审核状态，请等待重新审核。'),
    )
    return dict(r)


def reject_client_recharge(db, recharge_id, user_id):
    r = db.execute("SELECT * FROM client_recharges WHERE id=?", (recharge_id,)).fetchone()
    if not r:
        raise ValueError('充值记录不存在')
    if r['status'] != 'pending':
        raise ValueError('不在待确认状态')
    now = _now()
    db.execute(
        "UPDATE client_recharges SET status='rejected', confirmed_by=?, confirmed_at=? WHERE id=?",
        (user_id, now, recharge_id),
    )
    db.execute(
        """INSERT INTO client_messages (client_id, title, content, msg_type)
           VALUES (?, '充值申请被拒绝', ?, 'notice')""",
        (r['client_id'], f'您的充值申请 {r["amount"]:.2f} 元已被拒绝，请联系管理员了解详情。'),
    )
    return dict(r)


def record_client_outbound(db, customer_id, client_id, items, order_date=None,
                           remark='', user_id=None):
    """
    录入出库并扣减余额。items: [{item_name, quantity, unit_price, amount?, deduct_date?}]
    """
    client = primary_client_for_company(db, customer_id, client_id)
    if not client:
        raise ValueError('未找到有效客户账号，请先审核激活或绑定客户主数据')
    client_id = client['id']
    customer_id = client.get('customer_id') or customer_id
    company_name = client.get('company_name') or ''
    if customer_id:
        crow = db.execute("SELECT name FROM customers WHERE id=?", (customer_id,)).fetchone()
        if crow:
            company_name = crow['name']

    if not items:
        raise ValueError('请至少录入一条出库明细')

    now = _now()
    order_date = order_date or now[:10]
    count = db.execute("SELECT COUNT(*) FROM sales_orders").fetchone()[0]
    order_no = f'CC{datetime.now().strftime("%Y%m%d")}{str(count + 1).zfill(4)}'

    total_amount = 0.0
    total_qty = 0.0
    parsed = []
    for it in items:
        qty = float(it.get('quantity') or 0)
        price = float(it.get('unit_price') or 0)
        amount = float(it.get('amount') or 0)
        if amount <= 0 and qty > 0 and price > 0:
            amount = round(qty * price, 2)
        if amount <= 0:
            continue
        name = (it.get('item_name') or it.get('name') or '出库商品').strip()
        parsed.append({
            'item_name': name,
            'quantity': qty,
            'unit_price': price,
            'amount': amount,
            'truck_count': float(it.get('truck_count') or 0),
            'deduct_date': it.get('deduct_date') or order_date,
        })
        total_amount += amount
        total_qty += qty

    if not parsed:
        raise ValueError('没有有效的出库金额')

    cur = db.execute(
        """INSERT INTO sales_orders
           (project_id, contract_id, order_no, customer_name, customer_id,
            order_date, delivery_date, total_amount, total_quantity, status,
            remark, created_by, created_at, updated_at)
           VALUES (NULL, NULL, ?, ?, ?, ?, ?, ?, ?, 'delivered', ?, ?, ?, ?)""",
        (
            order_no, company_name, customer_id, order_date, order_date,
            total_amount, total_qty, remark or '客户协同录入', user_id, now, now,
        ),
    )
    order_id = cur.lastrowid
    deduct_count = 0
    for idx, it in enumerate(parsed):
        ic = db.execute(
            """INSERT INTO sales_order_items
               (order_id, sales_order_id, item_name, quantity, unit_price, amount, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (order_id, order_id, it['item_name'], it['quantity'], it['unit_price'],
             it['amount'], idx),
        )
        item_id = ic.lastrowid
        db.execute(
            """INSERT INTO client_deductions
               (client_id, sales_order_id, sales_item_id, amount, quantity,
                unit_price, item_name, truck_count, deduct_date, remark, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                client_id, order_id, item_id, it['amount'], it['quantity'],
                it['unit_price'], it['item_name'], it['truck_count'], it['deduct_date'],
                remark, now,
            ),
        )
        db.execute(
            """UPDATE client_accounts
               SET total_deduct=total_deduct+?, balance=balance-?, updated_at=?
               WHERE id=?""",
            (it['amount'], it['amount'], now, client_id),
        )
        deduct_count += 1

    return order_id, order_no, deduct_count, total_amount


def _normalize_payment_method(val):
    if not val:
        return 'bank_transfer'
    s = str(val).strip().lower()
    mapping = {
        '银行': 'bank_transfer', '转账': 'bank_transfer', 'bank': 'bank_transfer',
        '支付宝': 'alipay', 'alipay': 'alipay',
        '微信': 'wechat', 'wechat': 'wechat',
        '现金': 'cash', 'cash': 'cash',
    }
    for k, v in mapping.items():
        if k in s:
            return v
    if s in PAYMENT_METHODS:
        return s
    return 'other'


def _parse_float(val, default=0.0):
    if val is None or val == '':
        return default
    if isinstance(val, (int, float)):
        try:
            import math
            if math.isnan(val):
                return default
        except Exception:
            pass
        return float(val)
    s = re.sub(r'[^\d.\-]', '', str(val))
    try:
        return float(s) if s else default
    except ValueError:
        return default


def _cell_str(val):
    if val is None:
        return ''
    try:
        import pandas as pd
        if pd.isna(val):
            return ''
    except Exception:
        pass
    s = str(val).strip()
    return '' if s.lower() == 'nan' else s


def _cell_date(val):
    if val is None:
        return ''
    try:
        import pandas as pd
        if pd.isna(val):
            return ''
    except Exception:
        pass
    if hasattr(val, 'strftime'):
        return val.strftime('%Y-%m-%d')
    s = _cell_str(val)
    if not s:
        return ''
    m = re.search(r'(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s[:10]


def _excel_col_map(df):
    """表头 -> 原始列名（精确优先，再模糊）。"""
    exact = {str(c).strip(): c for c in df.columns}
    lower = {str(c).strip().lower(): c for c in df.columns}

    def find(*names):
        for n in names:
            if n in exact:
                return exact[n]
        for n in names:
            key = n.lower()
            if key in lower:
                return lower[key]
        for n in names:
            for h, orig in exact.items():
                if n in h or h == n:
                    return orig
        return None

    return find


def is_standard_collab_template(df):
    """识别标准模板：收款日期、金额、销售日期、规格、销售吨数、销售金额等。"""
    headers = [str(c).strip() for c in df.columns]
    hset = set(headers)
    if '销售金额' in hset and ('销售吨数' in hset or '规格' in hset):
        return True
    if '收款日期' in hset and '金额' in hset and ('销售日期' in hset or '规格' in hset):
        return True
    return False


def parse_collab_excel_standard(df):
    """
    标准列（与业务表格一致）：
    收款日期 | 金额 | 销售日期 | 规格 | 车数 | 销售吨数 | 单价 | 销售金额 | 余款 | 备注
  同一行可同时有收款（充值）与销售（出库扣减）。
    """
    find = _excel_col_map(df)
    c_pay_date = find('收款日期')
    c_pay_amount = find('金额')
    c_sales_date = find('销售日期')
    c_spec = find('规格')
    c_trucks = find('车数')
    c_tons = find('销售吨数')
    c_unit_price = find('单价')
    c_sales_amount = find('销售金额')
    c_balance = find('余款')
    c_remark = find('备注')

    if not c_pay_amount and not c_sales_amount and not c_tons:
        return {'error': '未识别标准模板列，请使用：收款日期、金额、销售日期、规格、车数、销售吨数、单价、销售金额、余款、备注'}

    recharge_rows = []
    outbound_rows = []
    records = df.to_dict('records')

    for idx, r in enumerate(records, 2):
        pay_amount = _parse_float(r.get(c_pay_amount)) if c_pay_amount else 0
        sales_amount = _parse_float(r.get(c_sales_amount)) if c_sales_amount else 0
        tons = _parse_float(r.get(c_tons)) if c_tons else 0
        unit_price = _parse_float(r.get(c_unit_price)) if c_unit_price else 0
        trucks = _parse_float(r.get(c_trucks)) if c_trucks else 0
        spec = _cell_str(r.get(c_spec)) if c_spec else ''
        remark = _cell_str(r.get(c_remark)) if c_remark else ''
        balance_note = _cell_str(r.get(c_balance)) if c_balance else ''

        extra = []
        if balance_note:
            extra.append(f'余款:{balance_note}')
        extra_txt = ' '.join(extra)

        if pay_amount > 0:
            pay_remark = remark
            if extra_txt and not sales_amount and not tons:
                pay_remark = f'{pay_remark} {extra_txt}'.strip()
            if trucks > 0 and not extra_txt:
                pay_remark = f'{pay_remark} {trucks:g}车'.strip()
            recharge_rows.append({
                'amount': pay_amount,
                'payment_method': 'bank_transfer',
                'payment_no': '',
                'remark': pay_remark or f'收款 {_cell_date(r.get(c_pay_date))}',
                'recharge_date': _cell_date(r.get(c_pay_date)) if c_pay_date else '',
            })

        if sales_amount <= 0 and tons > 0 and unit_price > 0:
            sales_amount = round(tons * unit_price, 2)

        # 销售单价为 0 或销售金额为 0 时不导入出库扣减
        if unit_price > 0 and sales_amount > 0:
            item_name = spec or '出库商品'
            ob_remark = remark
            if extra_txt:
                ob_remark = f'{ob_remark} {extra_txt}'.strip()
            outbound_rows.append({
                'item_name': item_name[:120],
                'quantity': tons,
                'unit_price': unit_price,
                'amount': sales_amount,
                'truck_count': trucks,
                'deduct_date': _cell_date(r.get(c_sales_date)) if c_sales_date else '',
                'remark': ob_remark,
            })

    if not recharge_rows and not outbound_rows:
        return {'error': '没有可导入的有效数据行（请填写「金额」或「销售金额」等）'}
    return {
        'template': 'standard',
        'recharge_rows': recharge_rows,
        'outbound_rows': outbound_rows,
    }


def import_standard_excel_bundle(db, customer_id, client_id, parsed, user_id, split_orders=False):
    """标准模板：同时导入充值与出库。"""
    recharge_rows = parsed.get('recharge_rows') or []
    outbound_rows = parsed.get('outbound_rows') or []
    parts = []
    errs = []

    if recharge_rows:
        ok, er = import_recharge_rows(db, client_id, recharge_rows, user_id)
        parts.append(f'充值 {ok} 条')
        errs.extend(er)

    if outbound_rows:
        cnt, total, order_no, er = import_outbound_rows(
            db, customer_id, client_id, outbound_rows, user_id,
            split_orders=split_orders,
        )
        if cnt > 0:
            msg = f'出库 {cnt} 条明细，扣减 {total:.2f} 元'
            if order_no:
                msg += f'（{order_no}）'
            parts.append(msg)
        errs.extend(er)

    if not parts:
        return False, '没有导入任何记录', errs
    return True, '；'.join(parts), errs


STANDARD_HEADER_TOKENS = ['收款日期', '金额', '销售日期', '规格', '车数',
                          '销售吨数', '单价', '销售金额', '余款', '备注']


def _detect_header_row(raw):
    """raw 为 header=None 读入的 DataFrame，定位标准表头所在行（跳过标题行）。"""
    scan = min(len(raw), 15)
    best_idx, best_hits = None, 0
    for i in range(scan):
        vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        hits = sum(1 for t in STANDARD_HEADER_TOKENS if t in vals)
        if hits > best_hits:
            best_hits, best_idx = hits, i
    if best_idx is not None and best_hits >= 3:
        return best_idx
    return None


def _load_sheet_df(pd, file_path, sheet):
    """读取指定页签并自动跳过标题行，返回规范化表头的 DataFrame。"""
    try:
        raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    except Exception:
        return None
    if raw is None or raw.empty:
        return None
    hdr = _detect_header_row(raw)
    if hdr is None:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except Exception:
            return None
    else:
        header = [str(v).strip() for v in raw.iloc[hdr].tolist()]
        df = raw.iloc[hdr + 1:].copy()
        df.columns = header
        df = df.reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how='all')
    return df


def parse_collab_excel(file_path, mode='recharge', sheet=None):
    """解析 Excel：自动定位表头行；支持多页签（sheet 指定，默认取首个有效页签）。"""
    try:
        import pandas as pd
    except ImportError:
        return {'error': '服务器未安装 pandas，无法导入 Excel'}

    try:
        xl = pd.ExcelFile(file_path)
    except Exception as e:
        return {'error': str(e)}

    sheet_names = list(xl.sheet_names)
    if sheet:
        if sheet not in sheet_names:
            return {'error': f'未找到页签「{sheet}」，可用页签：{"、".join(sheet_names)}',
                    'available_sheets': sheet_names}
        candidates = [sheet]
    else:
        candidates = sheet_names

    last_err = None
    for sn in candidates:
        df = _load_sheet_df(pd, file_path, sn)
        if df is None or df.empty:
            continue
        result = _parse_df_rows(df, mode)
        if result.get('error'):
            last_err = result['error']
            continue
        if not (result.get('rows') or result.get('recharge_rows') or result.get('outbound_rows')):
            continue
        result['used_sheet'] = sn
        result['available_sheets'] = sheet_names
        return result

    return {
        'error': last_err or '未识别标准模板列，请使用：收款日期、金额、销售日期、规格、车数、销售吨数、单价、销售金额、余款、备注',
        'available_sheets': sheet_names,
    }


def summarize_collab_excel_sheets(file_path, mode='standard'):
    """汇总每个页签的可导入内容，供用户勾选：返回 [{sheet, ok, recharge_count, recharge_amount,
    outbound_count, outbound_amount, date_min, date_max, error}]。"""
    try:
        import pandas as pd
    except ImportError:
        return {'error': '服务器未安装 pandas，无法导入 Excel'}
    try:
        xl = pd.ExcelFile(file_path)
    except Exception as e:
        return {'error': str(e)}

    import hashlib

    def _signature(rch, obd):
        parts = []
        for r in rch:
            parts.append('R|%s|%s' % (r.get('recharge_date') or '', round(float(r.get('amount') or 0), 2)))
        for r in obd:
            parts.append('O|%s|%s|%s|%s' % (
                r.get('deduct_date') or '',
                (r.get('item_name') or '').strip(),
                round(float(r.get('quantity') or 0), 3),
                round(float(r.get('amount') or 0), 2),
            ))
        parts.sort()
        return hashlib.md5('\n'.join(parts).encode('utf-8')).hexdigest()

    summaries = []
    seen_sig = {}
    for sn in xl.sheet_names:
        df = _load_sheet_df(pd, file_path, sn)
        if df is None or df.empty:
            continue
        res = _parse_df_rows(df, mode)
        if res.get('error'):
            continue
        rch = res.get('recharge_rows') or []
        obd = res.get('outbound_rows') or []
        if not rch and not obd:
            continue
        dates = [r.get('recharge_date') for r in rch if r.get('recharge_date')]
        dates += [r.get('deduct_date') for r in obd if r.get('deduct_date')]
        dates = [d for d in dates if d]
        sig = _signature(rch, obd)
        dup_of = seen_sig.get(sig)
        if not dup_of:
            seen_sig[sig] = sn
        summaries.append({
            'sheet': sn,
            'ok': True,
            'recharge_count': len(rch),
            'recharge_amount': round(sum(float(r.get('amount') or 0) for r in rch), 2),
            'outbound_count': len(obd),
            'outbound_amount': round(sum(float(r.get('amount') or 0) for r in obd), 2),
            'date_min': min(dates) if dates else '',
            'date_max': max(dates) if dates else '',
            'is_duplicate': bool(dup_of),
            'duplicate_of': dup_of or '',
        })
    return {'sheets': summaries, 'all_sheets': list(xl.sheet_names)}


def _parse_df_rows(df, mode):
    """对单个已规范化表头的 DataFrame 解析为可导入记录。"""
    if df is None or df.empty:
        return {'error': 'Excel 为空'}

    df.columns = [str(c).strip() for c in df.columns]

    if mode in ('auto', 'standard') or is_standard_collab_template(df):
        std = parse_collab_excel_standard(df)
        if not std.get('error'):
            return std
        if mode in ('auto', 'standard'):
            return std

    find = _excel_col_map(df)
    cols = {str(c).strip().lower(): c for c in df.columns}
    records = df.to_dict('records')
    rows = []

    def col(*names):
        for n in names:
            key = n.lower()
            if key in cols:
                return cols[key]
            for ck, cv in cols.items():
                if key in ck or ck in key:
                    return cv
        return None

    if mode == 'recharge':
        c_amount = find('金额') or col('充值金额', 'amount')
        c_date = find('收款日期') or col('日期', 'date', '交易日期')
        c_method = col('付款方式', 'payment', '方式')
        c_no = col('流水号', '单号', 'payment_no', '凭证号')
        c_remark = col('备注', 'remark')
        if not c_amount:
            return {'error': '未找到「金额」列，请使用列名：日期、金额、付款方式、备注'}
        for r in records:
            amount = _parse_float(r.get(c_amount))
            if amount <= 0:
                continue
            rows.append({
                'amount': amount,
                'payment_method': _normalize_payment_method(
                    r.get(c_method) if c_method else ''
                ),
                'payment_no': str(r.get(c_no) or '') if c_no else '',
                'remark': str(r.get(c_remark) or '') if c_remark else '',
                'recharge_date': str(r.get(c_date) or '')[:10] if c_date else '',
            })
    else:
        c_name = find('规格') or col('品名', '商品', '产品', '货物', 'item', '名称', 'item_name', '物料')
        c_qty = find('销售吨数') or col('数量', 'quantity', 'qty', '出库数量')
        c_price = find('单价') or col('unit_price', '价格', '含税单价')
        c_amount = find('销售金额') or col('amount', '合计', '总价', '出库金额')
        c_date = find('销售日期') or col('日期', 'date', '出库日期')
        c_trucks = find('车数')
        c_remark = col('备注', 'remark')
        if not c_name and not c_amount:
            return {'error': '未找到「品名」或「金额」列'}
        for r in records:
            name = _cell_str(r.get(c_name)) if c_name else ''
            if not name:
                name = '出库商品'
            qty = _parse_float(r.get(c_qty)) if c_qty else 0
            price = _parse_float(r.get(c_price)) if c_price else 0
            trucks = _parse_float(r.get(c_trucks)) if c_trucks else 0
            amount = _parse_float(r.get(c_amount)) if c_amount else 0
            if amount <= 0 and qty > 0 and price > 0:
                amount = round(qty * price, 2)
            if price <= 0:
                continue
            if amount <= 0:
                continue
            rows.append({
                'item_name': name[:120],
                'quantity': qty,
                'unit_price': price,
                'amount': amount,
                'truck_count': trucks,
                'deduct_date': _cell_date(r.get(c_date)) if c_date else '',
            })

    if not rows:
        return {'error': '没有可导入的有效数据行'}
    return {'rows': rows}


def import_recharge_rows(db, client_id, rows, user_id, auto_confirm=False):
    ok, errs = 0, []
    for i, row in enumerate(rows, 1):
        try:
            record_client_recharge(
                db, client_id,
                row['amount'],
                row.get('payment_method', 'bank_transfer'),
                row.get('payment_no', ''),
                row.get('remark', '') or row.get('recharge_date', ''),
                user_id=user_id,
                auto_confirm=auto_confirm,
            )
            ok += 1
        except Exception as e:
            errs.append(f'第{i}行: {e}')
    return ok, errs


def import_outbound_rows(db, customer_id, client_id, rows, user_id, split_orders=False):
    """导入出库：默认合并为一张出库单多明细；split_orders 时每行单独一单并扣减。"""
    if not rows:
        return 0, 0.0, '', ['没有可导入的出库数据']
    errs = []
    total_cnt = 0
    total_amount = 0.0
    order_nos = []
    batches = [[r] for r in rows] if split_orders else [rows]
    for i, batch in enumerate(batches, 1):
        try:
            _, order_no, cnt, amt = record_client_outbound(
                db, customer_id, client_id, batch, user_id=user_id,
            )
            total_cnt += cnt
            total_amount += amt
            if order_no:
                order_nos.append(order_no)
        except Exception as e:
            label = f'第{i}条' if split_orders else '批量'
            errs.append(f'{label}: {e}')
    if total_cnt == 0:
        return 0, 0.0, '', errs
    return total_cnt, total_amount, '、'.join(order_nos[:5]), errs


def _parse_date_from_line(line):
    m = re.search(
        r'(\d{4})\s*[-/年\.]\s*(\d{1,2})\s*[-/月\.]\s*(\d{1,2})',
        line,
    )
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if '今天' in line:
        return datetime.now().strftime('%Y-%m-%d')
    if '昨天' in line:
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    return None


def _parse_outbound_line(line):
    """从 OCR 单行解析品名、数量、单价、金额。"""
    if not line or len(line) < 2:
        return None
    skip_kw = (
        '合计', '总计', '小计', '出库单', '送货单', '发货单', '客户', '地址',
        '电话', '备注', '制单', '审核', '页码', '公司名称', '单据', '日期',
    )
    if any(k in line for k in skip_kw) and not re.search(r'\d+\.\d{2}', line):
        return None

    # 去掉行首序号 1. 1、 (1)
    work = re.sub(r'^[\d\.\)、\s]+', '', line.strip())
    work = work.replace('，', ',').replace('￥', '').replace('¥', '')

    # 品名|数量|单价|金额
    if '|' in work:
        parts = [p.strip() for p in work.split('|') if p.strip()]
        if len(parts) >= 2:
            nums = [_parse_float(p) for p in parts[1:]]
            amount = nums[-1] if nums else 0
            qty = nums[0] if len(nums) >= 2 else 0
            price = nums[1] if len(nums) >= 3 else 0
            if amount > 0 or (qty > 0 and price > 0):
                if amount <= 0:
                    amount = round(qty * price, 2)
                return {
                    'item_name': parts[0][:120],
                    'quantity': qty,
                    'unit_price': price,
                    'amount': amount,
                }

    # 末尾连续数字：数量、单价、金额 或 数量、金额 或 仅金额
    nums = []
    for m in re.finditer(r'(\d+(?:\.\d+)?)', work.replace(',', '')):
        v = float(m.group(1))
        if 1900 <= v <= 2100 and '.' not in m.group(1):
            continue
        nums.append((v, m.start()))
    if not nums:
        return None

    name = work[: nums[0][1]].strip(' \t:-—，,')
    if not name or len(name) < 1:
        name = '出库商品'
    values = [n[0] for n in nums]
    qty, price, amount = 0.0, 0.0, 0.0
    if len(values) >= 3:
        qty, price, amount = values[-3], values[-2], values[-1]
    elif len(values) == 2:
        qty, amount = values[0], values[1]
        if qty > 0:
            price = round(amount / qty, 4)
    else:
        amount = values[0]
    if amount <= 0 and qty > 0 and price > 0:
        amount = round(qty * price, 2)
    if amount <= 0:
        return None
    return {
        'item_name': name[:120],
        'quantity': qty,
        'unit_price': price,
        'amount': amount,
    }


def parse_outbound_ocr_text(text):
    """从 OCR 全文解析出库明细（支持多行多条）。"""
    if not text or '请安装' in text or '无法识别文字' in text:
        return []
    lines = [ln.strip() for ln in text.replace('\r', '').split('\n') if ln.strip()]
    if not lines:
        return []

    rows = []
    pending_date = datetime.now().strftime('%Y-%m-%d')
    header_mode = False
    col_qty = col_price = col_amount = -1

    for line in lines:
        d = _parse_date_from_line(line)
        if d:
            pending_date = d
            continue

        if re.search(r'品名|商品名称|货物名称|名称', line) and re.search(r'数量|金额', line):
            header_mode = True
            parts = re.split(r'[\s\t]+', line)
            col_qty = col_price = col_amount = -1
            for i, p in enumerate(parts):
                if '数量' in p:
                    col_qty = i
                if '单价' in p:
                    col_price = i
                if '金额' in p or '合计' in p:
                    col_amount = i
            continue

        if header_mode:
            parts = re.split(r'[\s\t]+', line)
            if len(parts) >= 2:
                try:
                    name = parts[0]
                    amount = 0.0
                    qty = price = 0.0
                    if col_amount >= 0 and col_amount < len(parts):
                        amount = _parse_float(parts[col_amount])
                    if col_qty >= 0 and col_qty < len(parts):
                        qty = _parse_float(parts[col_qty])
                    if col_price >= 0 and col_price < len(parts):
                        price = _parse_float(parts[col_price])
                    if amount <= 0 and len(parts) >= 2:
                        amount = _parse_float(parts[-1])
                    if qty <= 0 and len(parts) >= 3:
                        qty = _parse_float(parts[-3] if col_qty < 0 else parts[1])
                    if amount > 0:
                        rows.append({
                            'item_name': name[:120],
                            'quantity': qty,
                            'unit_price': price,
                            'amount': amount,
                            'deduct_date': pending_date,
                        })
                        continue
                except (ValueError, IndexError):
                    pass
            header_mode = False

        row = _parse_outbound_line(line)
        if row:
            row['deduct_date'] = pending_date
            rows.append(row)

    # 去重
    seen = set()
    unique = []
    for r in rows:
        key = (r['item_name'], r['amount'], r.get('deduct_date'))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def ocr_rows_for_outbound(transactions, raw_text=''):
    """出库 OCR：优先解析表格型送货单，回退到交易型 OCR 结果。"""
    rows = parse_outbound_ocr_text(raw_text)
    if rows:
        return rows
    for t in transactions or []:
        amount = _parse_float(t.get('amount'))
        if amount <= 0:
            continue
        desc = (t.get('merchant') or t.get('description') or t.get('raw_text') or '出库商品')[:120]
        rows.append({
            'item_name': desc,
            'quantity': 0,
            'unit_price': 0,
            'amount': amount,
            'deduct_date': (t.get('date') or '')[:10] or datetime.now().strftime('%Y-%m-%d'),
        })
    return rows


def ocr_rows_for_recharge(transactions):
    """从 OCR 交易结果提取充值候选。"""
    rows = []
    for t in transactions or []:
        amount = _parse_float(t.get('amount'))
        if amount <= 0:
            continue
        rows.append({
            'amount': amount,
            'payment_method': _normalize_payment_method(t.get('payment_method', '')),
            'payment_no': '',
            'remark': (t.get('merchant') or t.get('remark') or '')[:200],
            'trans_date': t.get('date', ''),
        })
    return rows


def save_upload_file(upload_folder, file, subdir='collab'):
    ext = os.path.splitext(file.filename)[1] or '.bin'
    name = f'{subdir}_{uuid.uuid4().hex[:12]}{ext}'
    folder = os.path.join(upload_folder, subdir)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    file.save(path)
    rel = f'{subdir}/{name}'
    return path, rel
