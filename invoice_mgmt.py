# -*- coding: utf-8 -*-
"""销售/采购发票管理：对照出库/采购明细汇总应开/已开/未开。"""

import re
from collections import defaultdict
from datetime import date

SALES_INVOICE_TYPES = ('sales', 'income', '收入发票', '销项发票')
PURCHASE_INVOICE_TYPES = ('purchase', 'cost', '成本发票', '进项发票', '支出发票')

GROUP_BY_LABELS = {
    'item_spec': '品名+规格',
    'item_name': '品名',
    'customer': '客户',
    'supplier': '供应商',
}

INVOICE_SCHEMA_DONE = False

EXCEL_COL_ALIASES = {
    'invoice_no': ('发票号码', '发票号', 'invoice_no'),
    'invoice_date': ('开票日期', '日期', 'invoice_date'),
    'amount': ('金额', '开票金额', '价税合计', 'total_amount', 'amount'),
    'tax_rate': ('税率', '税率%', 'tax_rate'),
    'tax_amount': ('税额', 'tax_amount'),
    'customer_name': ('客户', '客户名称', '购方', 'customer'),
    'supplier': ('供应商', '销方', 'supplier'),
    'item_name': ('品名', '货物名称', 'item_name'),
    'specification': ('规格', '规格型号', 'specification'),
    'quantity': ('数量', 'quantity'),
    'line_amount': ('明细金额', '行金额', 'line_amount'),
    'project_name': ('项目', '项目名称', 'project'),
    'remark': ('备注', 'remark'),
}


def purchase_date_column(db):
    cols = {r[1] for r in db.execute('PRAGMA table_info(purchase_orders)').fetchall()}
    for c in ('order_date', 'purchase_date', 'created_at'):
        if c in cols:
            return c
    return 'created_at'


def _sales_item_order_join(db):
    cols = {r[1] for r in db.execute('PRAGMA table_info(sales_order_items)').fetchall()}
    if 'sales_order_id' in cols and 'order_id' in cols:
        return '(soi.sales_order_id = so.id OR soi.order_id = so.id)'
    if 'sales_order_id' in cols:
        return 'soi.sales_order_id = so.id'
    return 'soi.order_id = so.id'


def _table_has_column(db, table, col):
    cols = {r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
    return col in cols


def ensure_invoice_schema(db):
    global INVOICE_SCHEMA_DONE
    db.execute("""
        CREATE TABLE IF NOT EXISTS invoice_summary_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            group_by TEXT NOT NULL,
            dim_primary TEXT NOT NULL,
            dim_secondary TEXT,
            allocated_amount REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
    """)
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_inv_alloc_dim ON invoice_summary_allocations(direction, group_by, dim_primary)'
    )
    if INVOICE_SCHEMA_DONE:
        db.commit()
        return
    for col, typ in (
        ('invoice_date', 'DATE'),
        ('status', "TEXT DEFAULT 'issued'"),
        ('attachment', 'TEXT'),
        ('created_by', 'INTEGER'),
        ('customer_name', 'TEXT'),
        ('supplier', 'TEXT'),
        ('biz_direction', 'TEXT'),
    ):
        if not _table_has_column(db, 'invoices', col):
            db.execute(f'ALTER TABLE invoices ADD COLUMN {col} {typ}')
    db.execute("""
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            item_name TEXT,
            specification TEXT,
            quantity REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            remark TEXT,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
    """)
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id)'
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_invoice_lines_item ON invoice_lines(item_name, specification)'
    )
    db.commit()
    INVOICE_SCHEMA_DONE = True


def make_row_key(dim_primary, dim_secondary=''):
    return f'{(dim_primary or "").strip()}\x1f{(dim_secondary or "").strip()}'


def parse_row_key(row_key):
    if not row_key:
        return '', ''
    parts = str(row_key).split('\x1f', 1)
    return parts[0], parts[1] if len(parts) > 1 else ''


def _qty_by_amount_ratio(source_qty, source_amt, invoiced_amt):
    if source_amt <= 0 or source_qty <= 0:
        return 0.0
    ratio = min(max(invoiced_amt / source_amt, 0.0), 1.0)
    return source_qty * ratio


def normalize_direction(invoice_type, biz_direction=None):
    if biz_direction in ('sales', 'purchase'):
        return biz_direction
    t = (invoice_type or '').strip().lower()
    if t in ('sales', 'income') or '收入' in (invoice_type or '') or '销项' in (invoice_type or ''):
        return 'sales'
    if t in ('purchase', 'cost') or '成本' in (invoice_type or '') or '进项' in (invoice_type or ''):
        return 'purchase'
    return 'sales'


def direction_invoice_types(direction):
    if direction == 'sales':
        return SALES_INVOICE_TYPES
    return PURCHASE_INVOICE_TYPES


def direction_label(direction):
    return '销售发票' if direction == 'sales' else '采购发票'


def default_invoice_type_value(direction):
    return 'sales' if direction == 'sales' else 'purchase'


def _is_sales_draft(status):
    return (status or '').strip() in ('待审核', 'pending', '待处理', 'draft', '草稿')


def _is_purchase_draft(status):
    return (status or '').strip() in ('draft', '草稿')


def _where(parts, params):
    if not parts:
        return '', params
    return ' WHERE ' + ' AND '.join(parts), params


def parse_hub_filters(request, default_include_draft=False):
    today = date.today()
    year_start = date(today.year, 1, 1)
    date_from = (request.args.get('date_from') or '').strip() or year_start.isoformat()
    date_to = (request.args.get('date_to') or '').strip() or today.isoformat()
    vals = request.args.getlist('include_draft')
    if vals:
        include_draft = str(vals[-1]).lower() in ('1', 'true', 'on', 'yes')
    else:
        include_draft = default_include_draft if not request.args else False
    group_by = (request.args.get('group_by') or 'item_spec').strip() or 'item_spec'
    return {
        'date_from': date_from,
        'date_to': date_to,
        'project_id': (request.args.get('project_id') or '').strip(),
        'customer_name': (request.args.get('customer_name') or '').strip(),
        'supplier': (request.args.get('supplier') or '').strip(),
        'item_name': (request.args.get('item_name') or '').strip(),
        'group_by': group_by,
        'include_draft': include_draft,
    }


def _valid_group_by(direction, group_by):
    if group_by == 'customer' and direction != 'sales':
        return 'item_spec'
    if group_by == 'supplier' and direction != 'purchase':
        return 'item_spec'
    if group_by not in GROUP_BY_LABELS:
        return 'item_spec'
    return group_by


def _group_key(row, group_by):
    if group_by == 'customer':
        name = (row.get('customer_name') or row.get('customer') or '').strip() or '未知客户'
        return (name,)
    if group_by == 'supplier':
        name = (row.get('supplier') or '').strip() or '未知供应商'
        return (name,)
    name = (row.get('item_name') or '').strip() or '未知品名'
    spec = (row.get('specification') or '').strip() or '-'
    if group_by == 'item_name':
        return (name,)
    return (name, spec)


def _merge_bucket(target, qty, amt):
    target['qty'] += float(qty or 0)
    target['amt'] += float(amt or 0)


def _bucket_factory():
    return {'qty': 0.0, 'amt': 0.0}


def _apply_hub_project_scope(db, filters, table_alias, parts, params):
    uid = filters.get('_scope_user_id')
    if uid is None:
        return
    from user_access import append_project_scope_to_parts
    append_project_scope_to_parts(
        db, uid, filters.get('_scope_role', ''), table_alias, parts, params,
    )


def _sales_source_buckets(db, filters):
    join_on = _sales_item_order_join(db)
    group_by = _valid_group_by('sales', filters.get('group_by') or 'item_spec')
    parts, params = [], []
    _apply_hub_project_scope(db, filters, 'so', parts, params)
    if filters.get('project_id'):
        parts.append('so.project_id=?')
        params.append(filters['project_id'])
    if filters.get('customer_name'):
        parts.append('so.customer_name LIKE ?')
        params.append(f'%{filters["customer_name"]}%')
    if filters.get('date_from'):
        parts.append('so.order_date>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append('so.order_date<=?')
        params.append(filters['date_to'])
    if filters.get('item_name') and group_by in ('item_spec', 'item_name'):
        parts.append('soi.item_name LIKE ?')
        params.append(f'%{filters["item_name"]}%')
    w, bind = _where(parts, params)
    rows = db.execute(f"""
        SELECT soi.item_name, soi.specification, so.customer_name as customer_name,
               COALESCE(soi.quantity, 0) as qty, COALESCE(soi.amount, 0) as amt, so.status
        FROM sales_orders so
        INNER JOIN sales_order_items soi ON {join_on}
        {w}
    """, bind).fetchall()
    buckets = defaultdict(_bucket_factory)
    for r in rows:
        if not filters.get('include_draft') and _is_sales_draft(r['status']):
            continue
        key = _group_key(dict(r), group_by)
        _merge_bucket(buckets[key], r['qty'], r['amt'])
    return buckets


def _purchase_source_buckets(db, filters):
    po_date = purchase_date_column(db)
    group_by = _valid_group_by('purchase', filters.get('group_by') or 'item_spec')
    parts, params = [], []
    _apply_hub_project_scope(db, filters, 'po', parts, params)
    if filters.get('project_id'):
        parts.append('po.project_id=?')
        params.append(filters['project_id'])
    if filters.get('supplier'):
        parts.append('po.supplier LIKE ?')
        params.append(f'%{filters["supplier"]}%')
    if filters.get('date_from'):
        parts.append(f'po.{po_date}>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append(f'po.{po_date}<=?')
        params.append(filters['date_to'])
    if filters.get('item_name') and group_by in ('item_spec', 'item_name'):
        parts.append('pi.item_name LIKE ?')
        params.append(f'%{filters["item_name"]}%')
    w, bind = _where(parts, params)
    rows = db.execute(f"""
        SELECT pi.item_name, pi.specification, po.supplier,
               COALESCE(pi.quantity, 0) as qty, COALESCE(pi.amount, 0) as amt, po.status
        FROM purchase_items pi
        JOIN purchase_orders po ON pi.purchase_id = po.id
        {w}
    """, bind).fetchall()
    buckets = defaultdict(_bucket_factory)
    for r in rows:
        if not filters.get('include_draft') and _is_purchase_draft(r['status']):
            continue
        key = _group_key(dict(r), group_by)
        _merge_bucket(buckets[key], r['qty'], r['amt'])
    return buckets


def _invoice_filter_parts(db, direction, filters):
    parts, params = [], []
    clause, cparams = _invoice_direction_clause(direction)
    parts.append(clause)
    params.extend(cparams)
    _apply_hub_project_scope(db, filters, 'i', parts, params)
    if filters.get('project_id'):
        parts.append('i.project_id=?')
        params.append(filters['project_id'])
    if direction == 'sales' and filters.get('customer_name'):
        parts.append('(i.customer_name LIKE ? OR i.customer_name IS NULL OR i.customer_name = "")')
        params.append(f'%{filters["customer_name"]}%')
    if direction == 'purchase' and filters.get('supplier'):
        parts.append('(i.supplier LIKE ? OR i.supplier IS NULL OR i.supplier = "")')
        params.append(f'%{filters["supplier"]}%')
    if filters.get('date_from'):
        parts.append('COALESCE(i.invoice_date, i.created_at)>=?')
        params.append(filters['date_from'])
    if filters.get('date_to'):
        parts.append('COALESCE(i.invoice_date, i.created_at)<=?')
        params.append(filters['date_to'])
    return parts, params


def _invoice_direction_clause(direction):
    types = direction_invoice_types(direction)
    ph = ','.join('?' * len(types))
    sql = f"(COALESCE(i.biz_direction, '') = ? OR i.invoice_type IN ({ph}))"
    return sql, [direction] + list(types)


def _invoice_invoiced_buckets(db, direction, filters):
    """已开/已收按发票分摊金额汇总，不按明细行逐条匹配。"""
    group_by = _valid_group_by(direction, filters.get('group_by') or 'item_spec')
    parts, params = _invoice_filter_parts(db, direction, filters)
    parts.append('a.direction=?')
    parts.append('a.group_by=?')
    params.extend([direction, group_by])
    w, bind = _where(parts, params)
    buckets = defaultdict(_bucket_factory)

    alloc_rows = db.execute(f"""
        SELECT a.dim_primary, a.dim_secondary, SUM(a.allocated_amount) as amt
        FROM invoice_summary_allocations a
        JOIN invoices i ON a.invoice_id = i.id
        {w}
        GROUP BY a.dim_primary, a.dim_secondary
    """, bind).fetchall()
    for r in alloc_rows:
        row = {
            'item_name': r['dim_primary'],
            'specification': r['dim_secondary'],
            'customer_name': r['dim_primary'],
            'supplier': r['dim_primary'],
        }
        key = _group_key(row, group_by)
        buckets[key]['amt'] += float(r['amt'] or 0)

    # 历史发票：无分摊记录时，按票头金额计入对应客户/供应商或「按票登记」
    legacy_parts, legacy_params = _invoice_filter_parts(db, direction, filters)
    lw, lbind = _where(legacy_parts, legacy_params)
    legacy_rows = db.execute(f"""
        SELECT i.id, i.amount, i.customer_name, i.supplier,
               (SELECT COALESCE(SUM(allocated_amount), 0) FROM invoice_summary_allocations
                WHERE invoice_id = i.id) as alloc_sum
        FROM invoices i {lw}
    """, lbind).fetchall()
    for inv in legacy_rows:
        if float(inv['alloc_sum'] or 0) > 0.001:
            continue
        amt = float(inv['amount'] or 0)
        if amt <= 0:
            continue
        if group_by == 'customer':
            row = {'customer_name': inv['customer_name']}
        elif group_by == 'supplier':
            row = {'supplier': inv['supplier']}
        else:
            row = {'item_name': '（按票登记·未分摊到品名）', 'specification': '-'}
        key = _group_key(row, group_by)
        buckets[key]['amt'] += amt
    return buckets


def build_item_summary(db, direction, filters):
    filters = dict(filters)
    filters['group_by'] = _valid_group_by(direction, filters.get('group_by') or 'item_spec')
    group_by = filters['group_by']

    if direction == 'sales':
        source = _sales_source_buckets(db, filters)
        source_label = '出库'
    else:
        source = _purchase_source_buckets(db, filters)
        source_label = '采购'

    invoiced = _invoice_invoiced_buckets(db, direction, filters)
    keys = set(source.keys()) | set(invoiced.keys())
    rows = []
    totals = {
        'source_qty': 0.0, 'source_amt': 0.0,
        'invoiced_qty': 0.0, 'invoiced_amt': 0.0,
        'open_qty': 0.0, 'open_amt': 0.0,
    }

    for key in sorted(keys, key=lambda k: (k[0], k[1] if len(k) > 1 else '')):
        s = source.get(key, _bucket_factory())
        inv = invoiced.get(key, _bucket_factory())
        invoiced_amt = inv['amt']
        invoiced_qty = _qty_by_amount_ratio(s['qty'], s['amt'], invoiced_amt)
        open_amt = s['amt'] - invoiced_amt
        open_qty = max(s['qty'] - invoiced_qty, 0.0)
        dim_primary = key[0]
        dim_secondary = key[1] if len(key) > 1 else ''
        rows.append({
            'item_name': dim_primary,
            'specification': dim_secondary or '-',
            'dim_primary': dim_primary,
            'dim_secondary': dim_secondary,
            'row_key': make_row_key(dim_primary, dim_secondary),
            'source_qty': s['qty'],
            'source_amt': s['amt'],
            'invoiced_qty': invoiced_qty,
            'invoiced_amt': invoiced_amt,
            'open_qty': open_qty,
            'open_amt': open_amt,
            'open_amt_negative': open_amt < -0.01,
        })
        totals['source_qty'] += s['qty']
        totals['source_amt'] += s['amt']
        totals['invoiced_qty'] += invoiced_qty
        totals['invoiced_amt'] += inv['amt']
        totals['open_qty'] += open_qty
        totals['open_amt'] += max(open_amt, 0.0)

    dim_primary_label = {
        'item_spec': '品名',
        'item_name': '品名',
        'customer': '客户',
        'supplier': '供应商',
    }.get(group_by, '维度')

    return {
        'rows': rows,
        'totals': totals,
        'source_label': source_label,
        'group_by': group_by,
        'group_by_label': GROUP_BY_LABELS.get(group_by, group_by),
        'dim_primary_label': dim_primary_label,
        'show_secondary': group_by == 'item_spec',
        'is_partner_group': group_by in ('customer', 'supplier'),
        'amount_only_mode': True,
    }


def list_invoices_for_direction(db, direction, filters, limit=200):
    parts, params = _invoice_filter_parts(db, direction, filters)
    w, bind = _where(parts, params)
    return db.execute(f"""
        SELECT i.*, i.invoice_no as invoice_number, p.name as project_name,
               c.contract_name,
               (SELECT COUNT(*) FROM invoice_lines il WHERE il.invoice_id = i.id) as line_count
        FROM invoices i
        LEFT JOIN projects p ON i.project_id = p.id
        LEFT JOIN contracts c ON i.contract_id = c.id
        {w}
        ORDER BY COALESCE(i.invoice_date, i.created_at) DESC, i.id DESC
        LIMIT ?
    """, bind + [limit]).fetchall()


def get_invoice_lines(db, invoice_id):
    return db.execute(
        'SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id',
        (invoice_id,),
    ).fetchall()


def load_invoice_for_edit(db, invoice_id):
    ensure_invoice_schema(db)
    from project_display import fetch_invoice_by_id
    invoice = fetch_invoice_by_id(db, invoice_id)
    if not invoice:
        return None, []
    return invoice, get_invoice_lines(db, invoice_id)


def parse_invoice_lines_from_form(form):
    names = form.getlist('line_item_name[]')
    specs = form.getlist('line_specification[]')
    qtys = form.getlist('line_quantity[]')
    amts = form.getlist('line_amount[]')
    lines = []
    n = max(len(names), len(specs), len(qtys), len(amts))
    for i in range(n):
        name = (names[i] if i < len(names) else '').strip()
        spec = (specs[i] if i < len(specs) else '').strip()
        try:
            qty = float(qtys[i]) if i < len(qtys) and qtys[i] else 0
        except (TypeError, ValueError):
            qty = 0
        try:
            amt = float(amts[i]) if i < len(amts) and amts[i] else 0
        except (TypeError, ValueError):
            amt = 0
        if not name and amt == 0 and qty == 0:
            continue
        if not name:
            name = '（明细）'
        unit_price = (amt / qty) if qty else 0
        lines.append({
            'item_name': name,
            'specification': spec or '-',
            'quantity': qty,
            'amount': amt,
            'unit_price': unit_price,
        })
    return lines


def _invoice_header_from_form(form, direction):
    amount = form.get('amount', type=float) or 0
    tax_rate = form.get('tax_rate', type=float) or 0
    tax_amount = form.get('tax_amount', type=float)
    if tax_amount is None:
        tax_amount = round(amount * tax_rate / 100, 2) if tax_rate else 0
    lines = parse_invoice_lines_from_form(form)
    if lines:
        line_amt = sum(l['amount'] for l in lines)
        if amount <= 0 and line_amt > 0:
            amount = line_amt
    return {
        'project_id': form.get('project_id', type=int),
        'contract_id': form.get('contract_id', type=int) or None,
        'invoice_no': (form.get('invoice_no') or '').strip(),
        'amount': amount,
        'tax_rate': tax_rate,
        'tax_amount': tax_amount,
        'invoice_date': (form.get('invoice_date') or '').strip() or None,
        'status': (form.get('status') or '').strip() or ('issued' if direction == 'sales' else 'received'),
        'remark': (form.get('remark') or '').strip(),
        'customer_name': (form.get('customer_name') or '').strip(),
        'supplier': (form.get('supplier') or '').strip(),
        'lines': lines,
    }


def _insert_invoice_lines(db, invoice_id, lines):
    for line in lines:
        db.execute("""
            INSERT INTO invoice_lines (invoice_id, item_name, specification, quantity, amount, unit_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            invoice_id, line['item_name'], line['specification'],
            line['quantity'], line['amount'], line['unit_price'],
        ))


def save_invoice(db, direction, form, user_id=None):
    ensure_invoice_schema(db)
    hdr = _invoice_header_from_form(form, direction)
    inv_type = default_invoice_type_value(direction)
    cols = {r[1] for r in db.execute('PRAGMA table_info(invoices)').fetchall()}
    fields = ['project_id', 'contract_id', 'invoice_no', 'invoice_type', 'amount',
              'tax_rate', 'tax_amount', 'remark']
    values = [
        hdr['project_id'], hdr['contract_id'], hdr['invoice_no'], inv_type,
        hdr['amount'], hdr['tax_rate'], hdr['tax_amount'], hdr['remark'],
    ]
    optional = (
        ('invoice_date', hdr['invoice_date']),
        ('status', hdr['status']),
        ('customer_name', hdr['customer_name'] if direction == 'sales' else None),
        ('supplier', hdr['supplier'] if direction == 'purchase' else None),
        ('biz_direction', direction),
        ('created_by', user_id),
    )
    for col, val in optional:
        if col in cols:
            fields.append(col)
            values.append(val)
    placeholders = ','.join('?' * len(fields))
    db.execute(
        f"INSERT INTO invoices ({', '.join(fields)}) VALUES ({placeholders})",
        values,
    )
    invoice_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    _insert_invoice_lines(db, invoice_id, hdr['lines'])
    db.commit()
    return invoice_id


def update_invoice(db, invoice_id, direction, form):
    ensure_invoice_schema(db)
    hdr = _invoice_header_from_form(form, direction)
    inv_type = default_invoice_type_value(direction)
    cols = {r[1] for r in db.execute('PRAGMA table_info(invoices)').fetchall()}
    sets = [
        'project_id=?', 'contract_id=?', 'invoice_no=?', 'invoice_type=?',
        'amount=?', 'tax_rate=?', 'tax_amount=?', 'remark=?',
    ]
    vals = [
        hdr['project_id'], hdr['contract_id'], hdr['invoice_no'], inv_type,
        hdr['amount'], hdr['tax_rate'], hdr['tax_amount'], hdr['remark'],
    ]
    if 'invoice_date' in cols:
        sets.append('invoice_date=?')
        vals.append(hdr['invoice_date'])
    if 'status' in cols:
        sets.append('status=?')
        vals.append(hdr['status'])
    if 'customer_name' in cols:
        sets.append('customer_name=?')
        vals.append(hdr['customer_name'] if direction == 'sales' else None)
    if 'supplier' in cols:
        sets.append('supplier=?')
        vals.append(hdr['supplier'] if direction == 'purchase' else None)
    if 'biz_direction' in cols:
        sets.append('biz_direction=?')
        vals.append(direction)
    vals.append(invoice_id)
    db.execute(f"UPDATE invoices SET {', '.join(sets)} WHERE id=?", vals)
    db.execute('DELETE FROM invoice_lines WHERE invoice_id=?', (invoice_id,))
    _insert_invoice_lines(db, invoice_id, hdr['lines'])
    db.commit()


def save_invoice_from_dict(db, direction, data, user_id=None):
    """OCR / Excel 单条写入。"""
    ensure_invoice_schema(db)
    lines = data.get('lines') or []
    amount = float(data.get('amount') or 0)
    if not amount and lines:
        amount = sum(float(l.get('amount') or 0) for l in lines)
    cols = {r[1] for r in db.execute('PRAGMA table_info(invoices)').fetchall()}
    fields = ['project_id', 'contract_id', 'invoice_no', 'invoice_type', 'amount',
              'tax_rate', 'tax_amount', 'remark']
    values = [
        data.get('project_id'), data.get('contract_id'),
        (data.get('invoice_no') or '').strip(),
        default_invoice_type_value(direction),
        amount,
        float(data.get('tax_rate') or 0),
        float(data.get('tax_amount') or 0),
        data.get('remark') or '',
    ]
    optional = (
        ('invoice_date', data.get('invoice_date')),
        ('status', data.get('status') or ('issued' if direction == 'sales' else 'received')),
        ('attachment', data.get('attachment')),
        ('customer_name', data.get('customer_name') if direction == 'sales' else None),
        ('supplier', data.get('supplier') if direction == 'purchase' else None),
        ('biz_direction', direction),
        ('created_by', user_id),
    )
    for col, val in optional:
        if col in cols:
            fields.append(col)
            values.append(val)
    placeholders = ','.join('?' * len(fields))
    db.execute(
        f"INSERT INTO invoices ({', '.join(fields)}) VALUES ({placeholders})",
        values,
    )
    invoice_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    if not lines and amount > 0:
        lines = [{
            'item_name': '（OCR/导入合计）',
            'specification': '-',
            'quantity': 0,
            'amount': amount,
            'unit_price': 0,
        }]
    _insert_invoice_lines(db, invoice_id, lines)
    db.commit()
    return invoice_id


def _normalize_excel_columns(df):
    import pandas as pd
    col_map = {}
    for c in df.columns:
        cs = str(c).strip()
        for key, aliases in EXCEL_COL_ALIASES.items():
            if cs in aliases or cs.lower() in [a.lower() for a in aliases]:
                col_map[c] = key
                break
    return df.rename(columns=col_map)


def _parse_float(val, default=0.0):
    if val is None or (isinstance(val, float) and val != val):
        return default
    try:
        s = str(val).replace(',', '').strip()
        if not s:
            return default
        return float(s)
    except (TypeError, ValueError):
        return default


def import_invoices_from_excel(file_storage, db, direction, default_project_id=None):
    import pandas as pd
    ensure_invoice_schema(db)
    df = pd.read_excel(file_storage)
    df = _normalize_excel_columns(df)
    if 'invoice_no' not in df.columns:
        return 0, 0, ['Excel 缺少「发票号码」列']

    projects = {
        (r['name'] or '').strip(): r['id']
        for r in db.execute('SELECT id, name FROM projects').fetchall()
    }
    errors = []
    saved = 0
    skipped = 0
    grouped = defaultdict(list)
    for _, row in df.iterrows():
        inv_no = str(row.get('invoice_no') or '').strip()
        if not inv_no or inv_no == 'nan':
            skipped += 1
            continue
        grouped[inv_no].append(row)

    for inv_no, rows in grouped.items():
        first = rows[0]
        pname = str(first.get('project_name') or '').strip()
        if pname == 'nan':
            pname = ''
        pid = projects.get(pname) or default_project_id
        lines = []
        for r in rows:
            item = str(r.get('item_name') or '').strip()
            if item == 'nan':
                item = ''
            amt = _parse_float(r.get('line_amount')) or _parse_float(r.get('amount'))
            qty = _parse_float(r.get('quantity'))
            if item or amt or qty:
                lines.append({
                    'item_name': item or '（明细）',
                    'specification': str(r.get('specification') or '-').strip() if str(r.get('specification') or '') != 'nan' else '-',
                    'quantity': qty,
                    'amount': amt,
                    'unit_price': (amt / qty) if qty else 0,
                })
        amount = _parse_float(first.get('amount'))
        if not amount and lines:
            amount = sum(l['amount'] for l in lines)
        if amount <= 0:
            errors.append(f'发票 {inv_no} 金额无效，已跳过')
            skipped += 1
            continue
        existing = db.execute(
            'SELECT id FROM invoices WHERE invoice_no=?', (inv_no,)
        ).fetchone()
        if existing:
            errors.append(f'发票号 {inv_no} 已存在，已跳过')
            skipped += 1
            continue
        data = {
            'project_id': pid,
            'invoice_no': inv_no,
            'amount': amount,
            'tax_rate': _parse_float(first.get('tax_rate')),
            'tax_amount': _parse_float(first.get('tax_amount')),
            'invoice_date': str(first.get('invoice_date') or '')[:10] if first.get('invoice_date') else None,
            'customer_name': str(first.get('customer_name') or '').strip() if direction == 'sales' else None,
            'supplier': str(first.get('supplier') or '').strip() if direction == 'purchase' else None,
            'remark': str(first.get('remark') or '') or 'Excel导入',
            'lines': lines,
        }
        if data['customer_name'] == 'nan':
            data['customer_name'] = None
        if data['supplier'] == 'nan':
            data['supplier'] = None
        try:
            save_invoice_from_dict(db, direction, data)
            saved += 1
        except Exception as e:
            errors.append(f'发票 {inv_no}: {e}')
            skipped += 1
    return saved, skipped, errors


def resolve_selections_from_summary(db, direction, filters, row_keys):
    """根据汇总行 key 解析当前未开金额（用于批量/部分开票）。"""
    summary = build_item_summary(db, direction, filters)
    by_key = {r['row_key']: r for r in summary['rows']}
    selections = []
    for rk in row_keys:
        rk = (rk or '').strip()
        if not rk:
            continue
        r = by_key.get(rk)
        if not r:
            continue
        open_amt = float(r.get('open_amt') or 0)
        if open_amt <= 0.001:
            continue
        selections.append({
            'dim_primary': r['dim_primary'],
            'dim_secondary': r.get('dim_secondary') or '',
            'open_amt': open_amt,
            'row_key': rk,
            'label': r['dim_primary'] + (
                f" / {r['dim_secondary']}" if summary.get('show_secondary') and r.get('dim_secondary') else ''
            ),
        })
    return selections, summary


def save_batch_invoice(db, direction, group_by, selections, issue_amount, form, user_id=None):
    """按总额开票：支持多选汇总项、部分金额（如100万开50万）。"""
    ensure_invoice_schema(db)
    group_by = _valid_group_by(direction, group_by)
    selections = [s for s in selections if float(s.get('open_amt') or 0) > 0.001]
    if not selections:
        raise ValueError('请至少选择一项未开金额大于0的汇总记录')
    total_open = sum(float(s['open_amt']) for s in selections)
    issue_amount = float(issue_amount or 0)
    if issue_amount <= 0:
        raise ValueError('本次开票金额须大于0')
    if issue_amount > total_open + 0.01:
        raise ValueError(f'本次开票金额不能超过所选未开合计 {total_open:.2f}')

    invoice_no = (form.get('invoice_no') or '').strip()
    if not invoice_no:
        raise ValueError('请填写发票号码')

    tax_rate = form.get('tax_rate', type=float) or 0
    tax_amount = form.get('tax_amount', type=float)
    if tax_amount is None:
        tax_amount = round(issue_amount * tax_rate / 100, 2) if tax_rate else 0

    partner_customer = (form.get('customer_name') or '').strip()
    partner_supplier = (form.get('supplier') or '').strip()
    if not partner_customer and direction == 'sales' and len(selections) == 1:
        if group_by == 'customer':
            partner_customer = selections[0]['dim_primary']
    if not partner_supplier and direction == 'purchase' and len(selections) == 1:
        if group_by == 'supplier':
            partner_supplier = selections[0]['dim_primary']

    inv_type = default_invoice_type_value(direction)
    cols = {r[1] for r in db.execute('PRAGMA table_info(invoices)').fetchall()}
    fields = ['project_id', 'contract_id', 'invoice_no', 'invoice_type', 'amount',
              'tax_rate', 'tax_amount', 'remark']
    values = [
        form.get('project_id', type=int),
        form.get('contract_id', type=int) or None,
        invoice_no, inv_type, issue_amount, tax_rate, tax_amount,
        (form.get('remark') or '').strip() or f'汇总开票·{len(selections)}项',
    ]
    optional = (
        ('invoice_date', (form.get('invoice_date') or '').strip() or None),
        ('status', (form.get('status') or '').strip() or ('issued' if direction == 'sales' else 'received')),
        ('customer_name', partner_customer if direction == 'sales' else None),
        ('supplier', partner_supplier if direction == 'purchase' else None),
        ('biz_direction', direction),
        ('created_by', user_id),
    )
    for col, val in optional:
        if col in cols:
            fields.append(col)
            values.append(val)
    placeholders = ','.join('?' * len(fields))
    db.execute(
        f"INSERT INTO invoices ({', '.join(fields)}) VALUES ({placeholders})",
        values,
    )
    invoice_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

    shares = []
    allocated = 0.0
    for i, sel in enumerate(selections):
        if i == len(selections) - 1:
            share = round(issue_amount - allocated, 2)
        else:
            share = round(issue_amount * float(sel['open_amt']) / total_open, 2)
            allocated += share
        shares.append(max(share, 0.0))
        db.execute("""
            INSERT INTO invoice_summary_allocations
            (invoice_id, direction, group_by, dim_primary, dim_secondary, allocated_amount)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            invoice_id, direction, group_by,
            sel['dim_primary'], sel.get('dim_secondary') or '',
            shares[-1],
        ))
    db.commit()
    return invoice_id


def hub_redirect_endpoint(direction):
    return 'invoice_sales' if direction == 'sales' else 'invoice_purchase'


def batch_issue_endpoint(direction):
    return 'invoice_sales_batch' if direction == 'sales' else 'invoice_purchase_batch'


def ocr_import_endpoint(direction):
    return 'invoice_sales_ocr_import' if direction == 'sales' else 'invoice_purchase_ocr_import'


def excel_import_endpoint(direction):
    return 'invoice_sales_import' if direction == 'sales' else 'invoice_purchase_import'
