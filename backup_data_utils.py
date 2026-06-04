# -*- coding: utf-8 -*-
"""备份库只读预览与按项目引入业务数据。"""

import sqlite3

PREVIEW_ROW_LIMIT = 100

# 预览统计项：(显示名, 表名, WHERE 子句)
PROJECT_PREVIEW_QUERIES = [
    ('合同', 'contracts', 'project_id = ?'),
    ('采购单', 'purchase_orders', 'project_id = ?'),
    ('销售出库单', 'sales_orders', 'project_id = ?'),
    ('费用记录', 'transaction_records', 'project_id = ?'),
    ('付款记录', 'payments', 'project_id = ?'),
    ('发票', 'invoices', 'project_id = ?'),
    ('投资记录', 'investments', 'project_id = ?'),
    ('分红记录', 'dividends', 'project_id = ?'),
    ('项目参与人', 'project_participants', 'project_id = ?'),
    ('运输记录', 'transport_records', 'project_id = ?'),
]

SUMMARY_LABELS = {
    'contract_amount': '合同金额',
    'purchase_amount': '采购单金额',
    'purchase_item_amount': '采购明细金额',
    'sales_amount': '销售出库金额',
    'sales_item_amount': '销售明细金额',
    'expense_amount': '费用支出',
    'income_amount': '费用收入',
    'payment_amount': '付款合计',
    'invoice_amount': '发票金额',
    'investment_amount': '投资合计',
    'dividend_amount': '分红合计',
    'transport_freight': '运费合计',
}


def _count_sales_items(conn, project_id):
    if not _table_exists(conn, 'sales_order_items') or not _table_exists(conn, 'sales_orders'):
        return None
    cols = {r[1] for r in conn.execute('PRAGMA table_info(sales_order_items)').fetchall()}
    if 'sales_order_id' in cols and 'order_id' in cols:
        sql = """SELECT COUNT(*) FROM sales_order_items soi
                 INNER JOIN sales_orders so ON (soi.sales_order_id = so.id OR soi.order_id = so.id)
                 WHERE so.project_id=?"""
    elif 'sales_order_id' in cols:
        sql = """SELECT COUNT(*) FROM sales_order_items soi
                 INNER JOIN sales_orders so ON soi.sales_order_id = so.id
                 WHERE so.project_id=?"""
    else:
        sql = """SELECT COUNT(*) FROM sales_order_items soi
                 INNER JOIN sales_orders so ON soi.order_id = so.id
                 WHERE so.project_id=?"""
    try:
        return conn.execute(sql, (project_id,)).fetchone()[0]
    except sqlite3.Error:
        return None


def _sales_items_join_sql_dynamic(conn):
    if not _table_exists(conn, 'sales_order_items'):
        return None, None
    cols = {r[1] for r in conn.execute('PRAGMA table_info(sales_order_items)').fetchall()}
    if 'sales_order_id' in cols and 'order_id' in cols:
        return (
            """FROM sales_order_items soi
               INNER JOIN sales_orders so ON (soi.sales_order_id = so.id OR soi.order_id = so.id)""",
            'soi.sales_order_id',
        )
    if 'sales_order_id' in cols:
        return (
            """FROM sales_order_items soi
               INNER JOIN sales_orders so ON soi.sales_order_id = so.id""",
            'soi.sales_order_id',
        )
    return (
        """FROM sales_order_items soi
           INNER JOIN sales_orders so ON soi.order_id = so.id""",
        'soi.order_id',
    )


def connect_backup_readonly(backup_path):
    """只读连接备份 SQLite 文件。"""
    uri = f'file:{backup_path}?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table):
    if not _table_exists(conn, table):
        return set()
    return {r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _safe_count(conn, table, where_sql, params):
    if not _table_exists(conn, table):
        return None
    try:
        return conn.execute(
            f'SELECT COUNT(*) FROM {table} WHERE {where_sql}',
            params,
        ).fetchone()[0]
    except sqlite3.Error:
        return None


def _safe_sum(conn, table, sum_col, where_sql, params):
    if not _table_exists(conn, table):
        return None
    cols = _table_columns(conn, table)
    if sum_col not in cols:
        return None
    try:
        return float(conn.execute(
            f'SELECT COALESCE(SUM({sum_col}), 0) FROM {table} WHERE {where_sql}',
            params,
        ).fetchone()[0] or 0)
    except sqlite3.Error:
        return None


def _serialize_cell(v):
    if v is None:
        return ''
    if isinstance(v, (int, float)):
        return round(float(v), 4) if isinstance(v, float) else v
    return str(v)[:200]


def _pick_columns(conn, table, candidates):
    """candidates: [(col, label), ...]，返回 [{key, label}, ...]。"""
    cols = _table_columns(conn, table)
    out = []
    seen = set()
    for col, label in candidates:
        if col in cols and col not in seen:
            out.append({'key': col, 'label': label})
            seen.add(col)
    return out


def _rows_to_list(rows, columns):
    result = []
    for row in rows:
        item = {}
        keys = row.keys() if hasattr(row, 'keys') else []
        for col in columns:
            k = col['key']
            item[k] = _serialize_cell(row[k] if k in keys else None)
        result.append(item)
    return result


def _fetch_limited(conn, sql, params):
    rows = conn.execute(sql + f' LIMIT {PREVIEW_ROW_LIMIT + 1}', params).fetchall()
    truncated = len(rows) > PREVIEW_ROW_LIMIT
    return rows[:PREVIEW_ROW_LIMIT], truncated


def _make_section(key, label, count, columns, rows, truncated, summary=None):
    if count is None or count == 0:
        return None
    sec = {
        'key': key,
        'label': label,
        'count': count,
        'columns': columns,
        'rows': rows,
        'truncated': truncated,
    }
    if summary:
        sec['summary'] = summary
    return sec


def _section_from_table(conn, key, label, table, where, params, col_candidates,
                        sum_col=None, order_by='id DESC'):
    if not _table_exists(conn, table):
        return None
    count = _safe_count(conn, table, where, params)
    if not count:
        return None
    columns = _pick_columns(conn, table, col_candidates)
    if not columns:
        columns = [{'key': 'id', 'label': 'ID'}]
    sel = ', '.join(c['key'] for c in columns)
    rows_raw, truncated = _fetch_limited(
        conn, f'SELECT {sel} FROM {table} WHERE {where} ORDER BY {order_by}', params,
    )
    summary = {}
    if sum_col:
        s = _safe_sum(conn, table, sum_col, where, params)
        if s is not None:
            summary['amount'] = round(s, 2)
    return _make_section(
        key, label, count, columns, _rows_to_list(rows_raw, columns), truncated, summary or None,
    )


def _compute_project_summary(conn, project_id):
    pid = (project_id,)
    s = {}
    v = _safe_sum(conn, 'contracts', 'amount', 'project_id = ?', pid)
    if v is not None:
        s['contract_amount'] = round(v, 2)
    v = _safe_sum(conn, 'purchase_orders', 'total_amount', 'project_id = ?', pid)
    if v is not None:
        s['purchase_amount'] = round(v, 2)
    if _table_exists(conn, 'purchase_items') and _table_exists(conn, 'purchase_orders'):
        try:
            v = conn.execute(
                """SELECT COALESCE(SUM(pi.amount), 0) FROM purchase_items pi
                   INNER JOIN purchase_orders po ON pi.purchase_id = po.id
                   WHERE po.project_id=?""", pid,
            ).fetchone()[0]
            s['purchase_item_amount'] = round(float(v or 0), 2)
        except sqlite3.Error:
            pass
    v = _safe_sum(conn, 'sales_orders', 'total_amount', 'project_id = ?', pid)
    if v is not None:
        s['sales_amount'] = round(v, 2)
    join_from, _ = _sales_items_join_sql_dynamic(conn)
    if join_from:
        try:
            v = conn.execute(
                f'SELECT COALESCE(SUM(soi.amount), 0) {join_from} WHERE so.project_id=?', pid,
            ).fetchone()[0]
            s['sales_item_amount'] = round(float(v or 0), 2)
        except sqlite3.Error:
            pass
    if _table_exists(conn, 'transaction_records'):
        cols = _table_columns(conn, 'transaction_records')
        if 'trans_type' in cols:
            for ttype, key in (('expense', 'expense_amount'), ('income', 'income_amount')):
                try:
                    v = conn.execute(
                        """SELECT COALESCE(SUM(amount), 0) FROM transaction_records
                           WHERE project_id=? AND trans_type=?""",
                        (project_id, ttype),
                    ).fetchone()[0]
                    s[key] = round(float(v or 0), 2)
                except sqlite3.Error:
                    pass
        else:
            v = _safe_sum(conn, 'transaction_records', 'amount', 'project_id = ?', pid)
            if v is not None:
                s['expense_amount'] = round(v, 2)
    elif _table_exists(conn, 'transactions'):
        v = _safe_sum(conn, 'transactions', 'amount', 'project_id = ?', pid)
        if v is not None:
            s['expense_amount'] = round(v, 2)
    v = _safe_sum(conn, 'payments', 'amount', 'project_id = ?', pid)
    if v is not None:
        s['payment_amount'] = round(v, 2)
    v = _safe_sum(conn, 'invoices', 'amount', 'project_id = ?', pid)
    if v is not None:
        s['invoice_amount'] = round(v, 2)
    v = _safe_sum(conn, 'investments', 'amount', 'project_id = ?', pid)
    if v is not None:
        s['investment_amount'] = round(v, 2)
    v = _safe_sum(conn, 'dividends', 'amount', 'project_id = ?', pid)
    if v is not None:
        s['dividend_amount'] = round(v, 2)
    freight_col = 'freight_amount' if 'freight_amount' in _table_columns(conn, 'transport_records') else None
    if freight_col:
        v = _safe_sum(conn, 'transport_records', freight_col, 'project_id = ?', pid)
        if v is not None:
            s['transport_freight'] = round(v, 2)
    return s


def _build_project_sections(conn, project_id):
    pid = (project_id,)
    sections = []

    sec = _section_from_table(
        conn, 'contracts', '合同', 'contracts', 'project_id = ?', pid,
        [
            ('contract_no', '合同编号'), ('contract_name', '合同名称'),
            ('contract_type', '类型'), ('party', '对方单位'), ('amount', '金额'),
            ('tax_rate', '税率'), ('remark', '备注'),
        ],
        sum_col='amount',
    )
    if sec:
        sections.append(sec)

    sec = _section_from_table(
        conn, 'purchase_orders', '采购单', 'purchase_orders', 'project_id = ?', pid,
        [
            ('purchase_no', '采购单号'), ('supplier', '供应商'), ('order_date', '日期'),
            ('total_amount', '金额'), ('status', '状态'), ('remark', '备注'),
        ],
        sum_col='total_amount',
    )
    if sec:
        sections.append(sec)

    if _table_exists(conn, 'purchase_items') and _table_exists(conn, 'purchase_orders'):
        count = conn.execute(
            """SELECT COUNT(*) FROM purchase_items pi
               INNER JOIN purchase_orders po ON pi.purchase_id = po.id
               WHERE po.project_id=?""", pid,
        ).fetchone()[0]
        if count:
            columns = [
                {'key': 'purchase_no', 'label': '采购单号'},
                {'key': 'supplier', 'label': '供应商'},
                {'key': 'item_name', 'label': '品名'},
                {'key': 'specification', 'label': '规格'},
                {'key': 'unit', 'label': '单位'},
                {'key': 'quantity', 'label': '数量'},
                {'key': 'unit_price', 'label': '单价'},
                {'key': 'amount', 'label': '金额'},
            ]
            pi_cols = _table_columns(conn, 'purchase_items')
            sel_parts = ['po.purchase_no', 'po.supplier']
            for c in ('item_name', 'specification', 'unit', 'quantity', 'unit_price', 'amount'):
                if c in pi_cols:
                    sel_parts.append(f'pi.{c} AS {c}')
            sql = f"""SELECT {', '.join(sel_parts)} FROM purchase_items pi
                      INNER JOIN purchase_orders po ON pi.purchase_id = po.id
                      WHERE po.project_id=? ORDER BY po.id DESC, pi.id"""
            rows_raw, truncated = _fetch_limited(conn, sql, pid)
            amt = conn.execute(
                """SELECT COALESCE(SUM(pi.amount), 0) FROM purchase_items pi
                   INNER JOIN purchase_orders po ON pi.purchase_id = po.id WHERE po.project_id=?""",
                pid,
            ).fetchone()[0]
            sec = _make_section(
                'purchase_items', '采购明细', count, columns,
                _rows_to_list(rows_raw, columns), truncated,
                {'amount': round(float(amt or 0), 2)},
            )
            if sec:
                sections.append(sec)

    sec = _section_from_table(
        conn, 'sales_orders', '销售出库单', 'sales_orders', 'project_id = ?', pid,
        [
            ('order_no', '出库单号'), ('customer_name', '客户'), ('order_date', '日期'),
            ('delivery_date', '交货日期'), ('total_amount', '金额'),
            ('total_quantity', '数量'), ('status', '状态'), ('remark', '备注'),
        ],
        sum_col='total_amount',
    )
    if sec:
        sections.append(sec)

    join_from, _ = _sales_items_join_sql_dynamic(conn)
    if join_from:
        try:
            count = conn.execute(
                f'SELECT COUNT(*) {join_from} WHERE so.project_id=?', pid,
            ).fetchone()[0]
        except sqlite3.Error:
            count = 0
        if count:
            soi_cols = _table_columns(conn, 'sales_order_items')
            sel_parts = ['so.order_no', 'so.customer_name']
            for c in ('item_name', 'specification', 'unit', 'quantity', 'unit_price', 'amount'):
                if c in soi_cols:
                    sel_parts.append(f'soi.{c} AS {c}')
            sql = f"""SELECT {', '.join(sel_parts)} {join_from}
                      WHERE so.project_id=? ORDER BY so.id DESC, soi.id"""
            rows_raw, truncated = _fetch_limited(conn, sql, pid)
            column_defs = [
                {'key': 'order_no', 'label': '出库单号'},
                {'key': 'customer_name', 'label': '客户'},
                {'key': 'item_name', 'label': '品名'},
                {'key': 'specification', 'label': '规格'},
                {'key': 'unit', 'label': '单位'},
                {'key': 'quantity', 'label': '数量'},
                {'key': 'unit_price', 'label': '单价'},
                {'key': 'amount', 'label': '金额'},
            ]
            keys = set(rows_raw[0].keys()) if rows_raw else set()
            columns = [c for c in column_defs if c['key'] in keys]
            amt = conn.execute(
                f'SELECT COALESCE(SUM(soi.amount), 0) {join_from} WHERE so.project_id=?', pid,
            ).fetchone()[0]
            sec = _make_section(
                'sales_order_items', '销售明细', count, columns,
                _rows_to_list(rows_raw, columns), truncated,
                {'amount': round(float(amt or 0), 2)},
            )
            if sec:
                sections.append(sec)

    expense_table = 'transaction_records' if _table_exists(conn, 'transaction_records') else (
        'transactions' if _table_exists(conn, 'transactions') else None
    )
    if expense_table:
        cols = _table_columns(conn, expense_table)
        candidates = [
            ('trans_date', '日期'), ('amount', '金额'), ('trans_type', '类型'),
            ('description', '说明'), ('merchant', '商户'), ('payer', '付款方'),
            ('payment_method', '方式'), ('remark', '备注'),
        ]
        if expense_table == 'transactions':
            candidates = [
                ('trans_date', '日期'), ('amount', '金额'), ('trans_type', '类型'),
                ('payer', '付款方'), ('payment_method', '方式'), ('remark', '备注'),
            ]
        sec = _section_from_table(
            conn, expense_table, '费用/往来记录', expense_table,
            'project_id = ?', pid, candidates, sum_col='amount',
        )
        if sec:
            sections.append(sec)

    sec = _section_from_table(
        conn, 'payments', '付款记录', 'payments', 'project_id = ?', pid,
        [
            ('payment_no', '付款编号'), ('payment_date', '日期'), ('amount', '金额'),
            ('payer', '付款方'), ('payment_method', '方式'), ('remark', '备注'),
        ],
        sum_col='amount',
    )
    if sec:
        sections.append(sec)

    sec = _section_from_table(
        conn, 'invoices', '发票', 'invoices', 'project_id = ?', pid,
        [
            ('invoice_no', '发票号'), ('invoice_type', '类型'), ('amount', '金额'),
            ('tax_rate', '税率'), ('tax_amount', '税额'), ('remark', '备注'),
        ],
        sum_col='amount',
    )
    if sec:
        sections.append(sec)

    if _table_exists(conn, 'invoice_lines') and _table_exists(conn, 'invoices'):
        try:
            count = conn.execute(
                """SELECT COUNT(*) FROM invoice_lines il
                   INNER JOIN invoices inv ON il.invoice_id = inv.id
                   WHERE inv.project_id=?""", pid,
            ).fetchone()[0]
        except sqlite3.Error:
            count = 0
        if count:
            columns = [
                {'key': 'invoice_no', 'label': '发票号'},
                {'key': 'item_name', 'label': '品名'},
                {'key': 'specification', 'label': '规格'},
                {'key': 'quantity', 'label': '数量'},
                {'key': 'amount', 'label': '金额'},
            ]
            sql = """SELECT inv.invoice_no, il.item_name, il.specification, il.quantity, il.amount
                     FROM invoice_lines il
                     INNER JOIN invoices inv ON il.invoice_id = inv.id
                     WHERE inv.project_id=? ORDER BY inv.id DESC, il.id"""
            rows_raw, truncated = _fetch_limited(conn, sql, pid)
            sec = _make_section(
                'invoice_lines', '发票明细', count, columns,
                _rows_to_list(rows_raw, columns), truncated,
            )
            if sec:
                sections.append(sec)

    if _table_exists(conn, 'investments'):
        cols = _table_columns(conn, 'investments')
        if 'participant_id' in cols and _table_exists(conn, 'participants'):
            count = _safe_count(conn, 'investments', 'project_id = ?', pid)
            if count:
                sql = """SELECT i.invest_date, i.amount, i.invest_type, i.payment_method, i.remark,
                                p.name AS participant_name
                         FROM investments i
                         LEFT JOIN participants p ON i.participant_id = p.id
                         WHERE i.project_id=? ORDER BY i.invest_date DESC, i.id DESC"""
                columns = [
                    {'key': 'invest_date', 'label': '日期'},
                    {'key': 'participant_name', 'label': '参与人'},
                    {'key': 'amount', 'label': '金额'},
                    {'key': 'invest_type', 'label': '类型'},
                    {'key': 'payment_method', 'label': '方式'},
                    {'key': 'remark', 'label': '备注'},
                ]
                rows_raw, truncated = _fetch_limited(conn, sql, pid)
                s = _safe_sum(conn, 'investments', 'amount', 'project_id = ?', pid)
                sec = _make_section(
                    'investments', '投资记录', count, columns,
                    _rows_to_list(rows_raw, columns), truncated,
                    {'amount': round(s or 0, 2)},
                )
                if sec:
                    sections.append(sec)
        else:
            sec = _section_from_table(
                conn, 'investments', '投资记录', 'investments', 'project_id = ?', pid,
                [('invest_date', '日期'), ('amount', '金额'), ('invest_type', '类型'), ('remark', '备注')],
                sum_col='amount',
            )
            if sec:
                sections.append(sec)

    if _table_exists(conn, 'dividends'):
        if _table_exists(conn, 'participants'):
            count = _safe_count(conn, 'dividends', 'project_id = ?', pid)
            if count:
                sql = """SELECT d.dividend_date, d.amount, d.period, d.payment_method, d.remark,
                                p.name AS participant_name
                         FROM dividends d
                         LEFT JOIN participants p ON d.participant_id = p.id
                         WHERE d.project_id=? ORDER BY d.dividend_date DESC, d.id DESC"""
                columns = [
                    {'key': 'dividend_date', 'label': '日期'},
                    {'key': 'participant_name', 'label': '参与人'},
                    {'key': 'amount', 'label': '金额'},
                    {'key': 'period', 'label': '期间'},
                    {'key': 'payment_method', 'label': '方式'},
                    {'key': 'remark', 'label': '备注'},
                ]
                rows_raw, truncated = _fetch_limited(conn, sql, pid)
                s = _safe_sum(conn, 'dividends', 'amount', 'project_id = ?', pid)
                sec = _make_section(
                    'dividends', '分红记录', count, columns,
                    _rows_to_list(rows_raw, columns), truncated,
                    {'amount': round(s or 0, 2)},
                )
                if sec:
                    sections.append(sec)
        else:
            sec = _section_from_table(
                conn, 'dividends', '分红记录', 'dividends', 'project_id = ?', pid,
                [('dividend_date', '日期'), ('amount', '金额'), ('period', '期间'), ('remark', '备注')],
                sum_col='amount',
            )
            if sec:
                sections.append(sec)

    if _table_exists(conn, 'transport_records'):
        tr_cols = _table_columns(conn, 'transport_records')
        candidates = [
            ('transport_date', '运输日期'), ('batch_no', '批次'), ('vehicle_no', '车号'),
            ('driver_name', '司机'), ('quantity', '数量'), ('unit_price', '单价'),
            ('freight_amount', '运费'), ('remark', '备注'),
        ]
        candidates = [(c, l) for c, l in candidates if c in tr_cols]
        sec = _section_from_table(
            conn, 'transport_records', '运输记录', 'transport_records',
            'project_id = ?', pid, candidates,
            sum_col='freight_amount' if 'freight_amount' in tr_cols else None,
        )
        if sec:
            sections.append(sec)

    if _table_exists(conn, 'project_participants') and _table_exists(conn, 'participants'):
        count = _safe_count(conn, 'project_participants', 'project_id = ?', pid)
        if count:
            sql = """SELECT p.name AS participant_name, pp.project_role, pp.investment_ratio,
                            pp.dividend_ratio, pp.joined_at
                     FROM project_participants pp
                     LEFT JOIN participants p ON pp.participant_id = p.id
                     WHERE pp.project_id=? ORDER BY pp.id"""
            columns = [
                {'key': 'participant_name', 'label': '参与人'},
                {'key': 'project_role', 'label': '角色'},
                {'key': 'investment_ratio', 'label': '投资比例%'},
                {'key': 'dividend_ratio', 'label': '分红比例%'},
                {'key': 'joined_at', 'label': '加入时间'},
            ]
            rows_raw, truncated = _fetch_limited(conn, sql, pid)
            sec = _make_section(
                'project_participants', '项目参与人', count, columns,
                _rows_to_list(rows_raw, columns), truncated,
            )
            if sec:
                sections.append(sec)

    return sections


def _project_counts(conn, project_id):
    counts = []
    total = 0
    for label, table, where in PROJECT_PREVIEW_QUERIES:
        n = _safe_count(conn, table, where, (project_id,))
        if n is None:
            continue
        counts.append({'label': label, 'table': table, 'count': n})
        total += n

    if _table_exists(conn, 'purchase_items') and _table_exists(conn, 'purchase_orders'):
        n = conn.execute(
            """SELECT COUNT(*) FROM purchase_items pi
               INNER JOIN purchase_orders po ON pi.purchase_id = po.id
               WHERE po.project_id=?""",
            (project_id,),
        ).fetchone()[0]
        counts.append({'label': '采购明细', 'table': 'purchase_items', 'count': n})
        total += n

    n = _count_sales_items(conn, project_id)
    if n is not None:
        counts.append({'label': '销售明细', 'table': 'sales_order_items', 'count': n})
        total += n

    return counts, total


def list_projects_in_backup(backup_path):
    """返回备份中的项目列表 [{id, name, status, ...}]。"""
    conn = connect_backup_readonly(backup_path)
    try:
        if not _table_exists(conn, 'projects'):
            return []
        rows = conn.execute(
            'SELECT id, name, status, budget FROM projects ORDER BY name'
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def preview_backup_file(backup_path, source_project_id=None):
    """
    预览备份内容。
    source_project_id 为空时返回全库概览；否则返回指定项目各表数量。
    """
    conn = connect_backup_readonly(backup_path)
    try:
        if source_project_id:
            return _preview_one_project(conn, source_project_id)
        return _preview_whole_backup(conn)
    finally:
        conn.close()


def _preview_whole_backup(conn):
    projects = []
    global_summary = {}
    if _table_exists(conn, 'projects'):
        for r in conn.execute(
            'SELECT id, name, status FROM projects ORDER BY id'
        ).fetchall():
            pid = r['id']
            counts, total_rows = _project_counts(conn, pid)
            summary = _compute_project_summary(conn, pid)
            projects.append({
                'id': pid,
                'name': r['name'],
                'status': r['status'],
                'counts': counts,
                'total_rows': total_rows,
                'summary': summary,
            })
            for k, v in summary.items():
                global_summary[k] = round(global_summary.get(k, 0) + float(v or 0), 2)

    return {
        'mode': 'file',
        'project_count': len(projects),
        'projects': projects[:50],
        'truncated': len(projects) > 50,
        'summary': global_summary,
        'summary_labels': SUMMARY_LABELS,
    }


def _preview_one_project(conn, project_id):
    project = None
    if _table_exists(conn, 'projects'):
        project = conn.execute(
            'SELECT id, name, status, budget, description FROM projects WHERE id=?',
            (project_id,),
        ).fetchone()
    if not project:
        return {'mode': 'project', 'error': '备份中不存在该项目'}

    counts, total = _project_counts(conn, project_id)
    summary = _compute_project_summary(conn, project_id)
    sections = _build_project_sections(conn, project_id)

    return {
        'mode': 'project',
        'project': dict(project),
        'counts': counts,
        'total_rows': total,
        'summary': summary,
        'summary_labels': SUMMARY_LABELS,
        'sections': sections,
    }


def import_project_data_from_backup(main_db, backup_path, source_project_id, target_project_id):
    """
    从备份库将指定项目的业务数据复制到主库新项目。
    返回 (成功, 消息, 统计 dict)。
    """
    src = connect_backup_readonly(backup_path)
    try:
        proj = src.execute('SELECT id, name FROM projects WHERE id=?', (source_project_id,)).fetchone()
        if not proj:
            return False, '备份中找不到源项目', {}

        stats = {}
        contract_map = _import_table_by_project(
            src, main_db, 'contracts', source_project_id, target_project_id,
            stats, fk_maps={'contract_id': None},
        )
        po_map = _import_purchase_chain(src, main_db, source_project_id, target_project_id, contract_map, stats)
        so_map = _import_sales_chain(src, main_db, source_project_id, target_project_id, contract_map, stats)
        _import_transports(src, main_db, source_project_id, target_project_id, po_map, so_map, stats)
        _import_simple_tables(src, main_db, source_project_id, target_project_id, stats)
        if _table_exists(src, 'project_categories'):
            _copy_rows(
                src, main_db, 'project_categories',
                'project_id=?', (source_project_id,),
                {'project_id': target_project_id}, stats, 'project_categories',
            )
        if _table_exists(src, 'project_participants'):
            _copy_rows(
                src, main_db, 'project_participants',
                'project_id=?', (source_project_id,),
                {'project_id': target_project_id}, stats, 'project_participants',
            )

        return True, f'已从备份引入项目「{proj["name"]}」的业务数据', stats
    except sqlite3.Error as e:
        return False, f'引入失败：{e}', {}
    finally:
        src.close()


def _import_table_by_project(src, main_db, table, src_pid, dst_pid, stats, fk_maps=None):
    """按 project_id 复制表数据，返回 old_id -> new_id 映射。"""
    id_map = {}
    if not _table_exists(src, table) or not _table_exists(main_db, table):
        return id_map
    rows = src.execute(f'SELECT * FROM {table} WHERE project_id=?', (src_pid,)).fetchall()
    for row in rows:
        new_id = _insert_row_copy(main_db, table, row, {'project_id': dst_pid})
        id_map[row['id']] = new_id
    stats[table] = len(id_map)
    return id_map


def _import_simple_tables(src, main_db, src_pid, dst_pid, stats):
    for table in (
        'transaction_records', 'transactions', 'payments', 'invoices',
        'investments', 'dividends',
    ):
        _copy_rows(
            src, main_db, table,
            'project_id=?', (src_pid,),
            {'project_id': dst_pid}, stats, table,
        )


def _import_purchase_chain(src, main_db, src_pid, dst_pid, contract_map, stats):
    po_map = {}
    if not _table_exists(src, 'purchase_orders'):
        return po_map
    rows = src.execute(
        'SELECT * FROM purchase_orders WHERE project_id=?', (src_pid,)
    ).fetchall()
    for row in rows:
        overrides = {'project_id': dst_pid}
        if row['contract_id'] and contract_map and row['contract_id'] in contract_map:
            overrides['contract_id'] = contract_map[row['contract_id']]
        new_id = _insert_row_copy(main_db, 'purchase_orders', row, overrides)
        po_map[row['id']] = new_id
    stats['purchase_orders'] = len(po_map)

    item_count = 0
    if _table_exists(src, 'purchase_items') and po_map:
        for old_po, new_po in po_map.items():
            items = src.execute(
                'SELECT * FROM purchase_items WHERE purchase_id=?', (old_po,)
            ).fetchall()
            for it in items:
                _insert_row_copy(main_db, 'purchase_items', it, {'purchase_id': new_po})
                item_count += 1
    stats['purchase_items'] = item_count

    if _table_exists(src, 'reconciliations') and po_map:
        rc = 0
        for old_po, new_po in po_map.items():
            recs = src.execute(
                'SELECT * FROM reconciliations WHERE purchase_id=?', (old_po,)
            ).fetchall()
            for rec in recs:
                _insert_row_copy(main_db, 'reconciliations', rec, {'purchase_id': new_po})
                rc += 1
        stats['reconciliations'] = rc
    return po_map


def _import_sales_chain(src, main_db, src_pid, dst_pid, contract_map, stats):
    so_map = {}
    if not _table_exists(src, 'sales_orders'):
        return so_map
    rows = src.execute(
        'SELECT * FROM sales_orders WHERE project_id=?', (src_pid,)
    ).fetchall()
    for row in rows:
        overrides = {'project_id': dst_pid}
        if row['contract_id'] and contract_map and row['contract_id'] in contract_map:
            overrides['contract_id'] = contract_map[row['contract_id']]
        new_id = _insert_row_copy(main_db, 'sales_orders', row, overrides)
        so_map[row['id']] = new_id
    stats['sales_orders'] = len(so_map)

    item_map = {}
    item_count = 0
    if _table_exists(src, 'sales_order_items') and so_map:
        cols = {r[1] for r in src.execute('PRAGMA table_info(sales_order_items)').fetchall()}
        for old_so, new_so in so_map.items():
            if 'sales_order_id' in cols:
                items = src.execute(
                    'SELECT * FROM sales_order_items WHERE sales_order_id=?', (old_so,)
                ).fetchall()
            else:
                items = src.execute(
                    'SELECT * FROM sales_order_items WHERE order_id=?', (old_so,)
                ).fetchall()
            for it in items:
                ovr = {'sales_order_id': new_so, 'order_id': new_so}
                new_item_id = _insert_row_copy(main_db, 'sales_order_items', it, ovr)
                item_map[it['id']] = new_item_id
                item_count += 1
    stats['sales_order_items'] = item_count
    return so_map


def _import_transports(src, main_db, src_pid, dst_pid, po_map, so_map, stats):
    if not _table_exists(src, 'transport_records'):
        return
    tr_cols = {r[1] for r in src.execute('PRAGMA table_info(transport_records)').fetchall()}
    tr_map = {}
    rows = src.execute(
        'SELECT * FROM transport_records WHERE project_id=?', (src_pid,)
    ).fetchall()
    old_po_ids = set(po_map.keys())
    for row in rows:
        overrides = {'project_id': dst_pid}
        if 'purchase_id' in tr_cols and row['purchase_id'] in po_map:
            overrides['purchase_id'] = po_map[row['purchase_id']]
        if 'sales_order_id' in tr_cols and row['sales_order_id'] in so_map:
            overrides['sales_order_id'] = so_map[row['sales_order_id']]
        new_id = _insert_row_copy(main_db, 'transport_records', row, overrides)
        tr_map[row['id']] = new_id

    if 'purchase_id' in tr_cols and old_po_ids:
        ph = ','.join('?' * len(old_po_ids))
        extra = src.execute(
            f'SELECT * FROM transport_records WHERE purchase_id IN ({ph}) AND (project_id IS NULL OR project_id=0)',
            tuple(old_po_ids),
        ).fetchall()
        for row in extra:
            if row['id'] in tr_map:
                continue
            overrides = {'project_id': dst_pid, 'purchase_id': po_map.get(row['purchase_id'])}
            tr_map[row['id']] = _insert_row_copy(main_db, 'transport_records', row, overrides)

    stats['transport_records'] = len(tr_map)

    if _table_exists(src, 'transport_purchase_items') and tr_map:
        n = 0
        for old_tr, new_tr in tr_map.items():
            links = src.execute(
                'SELECT * FROM transport_purchase_items WHERE transport_id=?', (old_tr,)
            ).fetchall()
            for lk in links:
                ovr = {'transport_id': new_tr}
                if lk['purchase_item_id']:
                    pass
                _insert_row_copy(main_db, 'transport_purchase_items', lk, ovr)
                n += 1
        stats['transport_purchase_items'] = n


def _copy_rows(src, main_db, table, where, params, overrides, stats, stat_key):
    if not _table_exists(src, table) or not _table_exists(main_db, table):
        return
    rows = src.execute(f'SELECT * FROM {table} WHERE {where}', params).fetchall()
    n = 0
    for row in rows:
        _insert_row_copy(main_db, table, row, overrides)
        n += 1
    stats[stat_key] = n


def _insert_row_copy(main_db, table, row, overrides=None, fk_remap=None):
    """插入一行（跳过 id），应用 overrides 字段覆盖。"""
    overrides = overrides or {}
    fk_remap = fk_remap or {}
    data = dict(row)
    data.pop('id', None)
    for k, v in overrides.items():
        if v is not None or k in data:
            data[k] = v
    for fk_col, id_map in (fk_remap or {}).items():
        if fk_col in data and data[fk_col] in id_map:
            data[fk_col] = id_map[data[fk_col]]
    main_cols = {r[1] for r in main_db.execute(f'PRAGMA table_info({table})').fetchall()}
    data = {k: v for k, v in data.items() if k in main_cols}
    if not data:
        return None
    cols = ', '.join(data.keys())
    ph = ', '.join('?' * len(data))
    cur = main_db.execute(
        f'INSERT INTO {table} ({cols}) VALUES ({ph})',
        list(data.values()),
    )
    return cur.lastrowid
