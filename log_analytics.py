# -*- coding: utf-8 -*-
"""操作日志筛选、按天汇总、用户行为分析、功能访问统计。"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime

# 路由 endpoint → (功能键, 功能名称)
ENDPOINT_FEATURES = {
    'dashboard': ('dashboard', '工作台'),
    'project_list': ('project', '项目列表'),
    'project_add': ('project', '新建项目'),
    'project_detail': ('project', '项目详情'),
    'project_edit': ('project', '编辑项目'),
    'participant_list': ('participant', '参与人'),
    'purchase_list': ('purchase', '采购单列表'),
    'purchase_detail': ('purchase', '采购单详情'),
    'purchase_add': ('purchase', '新建采购单'),
    'purchase_edit': ('purchase', '编辑采购单'),
    'sales_order_list': ('sales', '销售出库列表'),
    'sales_order_detail': ('sales', '销售出库详情'),
    'sales_order_add': ('sales', '新建销售出库'),
    'sales_order_edit': ('sales', '编辑销售出库'),
    'contract_list': ('contract', '合同管理'),
    'invoice_list': ('invoice', '发票管理'),
    'invoice_sales_hub': ('invoice', '销售发票'),
    'invoice_purchase_hub': ('invoice', '采购发票'),
    'payment_list': ('payment', '付款管理'),
    'transaction_list': ('transaction', '费用记录'),
    'report_hub': ('report', '报表中心'),
    'report_view': ('report', '报表查看'),
    'reconciliation_center': ('reconciliation', '对账中心'),
    'supplier_list': ('supplier', '供应商'),
    'customer_list': ('customer', '客户管理'),
    'category_list': ('category', '费用分类'),
    'account_manage': ('account', '账号管理'),
    'backup_manage': ('backup', '备份管理'),
    'log_list': ('logs', '操作日志'),
    'log_analytics': ('logs', '日志分析'),
    'base_data': ('base_data', '基础资料'),
    'admin_client_dashboard': ('collab', '客户协同总览'),
    'admin_client_recharges': ('collab', '客户充值'),
    'admin_client_reports': ('collab', '协同报表'),
    'admin_collab_user_mgmt': ('collab', '协同账号'),
    'ocr_list': ('ocr', 'OCR识别'),
    'transport_list': ('transport', '运输管理'),
}

DOC_TYPE_LABELS = {
    'purchase_order': '采购单',
    'sales_order': '销售出库单',
    'contract': '合同',
    'invoice': '发票',
    'payment': '付款记录',
    'transaction': '费用/交易记录',
    'investment': '投资记录',
    'dividend': '分红记录',
    'transport': '运输记录',
    'project': '项目',
    'participant': '参与人',
    'reconciliation': '对账',
    'collab_recharge': '客户充值',
    'collab_deduction': '客户扣减',
    'sales_payment': '销售回款',
    'account': '系统账号',
    'backup': '备份',
    'other': '其他',
}

MODULE_LABELS = {
    'project': '项目',
    'purchase': '采购',
    'sales': '销售',
    'contract': '合同',
    'invoice': '发票',
    'payment': '付款',
    'transaction': '费用/交易',
    'investment': '投资',
    'dividend': '分红',
    'transport': '运输',
    'reconciliation': '对账',
    'report': '报表',
    'collab': '客户协同',
    'account': '账号',
    'backup': '备份',
    'ocr': 'OCR',
    'system': '系统',
    'auth': '登录认证',
    'other': '其他',
}

OP_TYPE_LABELS = {
    'create': '新增',
    'import': '导入',
    'update': '修改',
    'delete': '删除',
    'submit': '提交',
    'unsubmit': '反提交',
    'confirm': '确认/审核',
    'other': '其他',
}

DOC_ACTION_KEYWORDS = (
    '新增', '修改', '删除', '编辑', '提交', '反提交', '导入', '确认', '审核',
    '对账', '入账', '同步', '批量',
)

CHART_COLORS = [
    '#0d6efd', '#198754', '#dc3545', '#ffc107', '#6f42c1',
    '#fd7e14', '#20c997', '#0dcaf0', '#d63384', '#6c757d',
]


def ensure_log_schema(db):
    """扩展 logs 表并创建功能访问统计表。"""
    cols = {r[1] for r in db.execute('PRAGMA table_info(logs)').fetchall()}
    migrations = [
        ('feature_module', 'TEXT'),
        ('entity_count', 'INTEGER DEFAULT 0'),
        ('doc_type', 'TEXT'),
        ('op_type', 'TEXT'),
        ('doc_count', 'INTEGER DEFAULT 0'),
    ]
    for col, typedef in migrations:
        if col not in cols:
            db.execute(f'ALTER TABLE logs ADD COLUMN {col} {typedef}')
    db.execute("""
        CREATE TABLE IF NOT EXISTS log_feature_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            feature_key TEXT NOT NULL,
            feature_label TEXT,
            route_path TEXT,
            access_date DATE NOT NULL,
            access_count INTEGER DEFAULT 1,
            first_access_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_access_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, feature_key, access_date)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_logs_username ON logs(username)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_logs_doc_type ON logs(doc_type)")
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_feature_access_date
        ON log_feature_access(access_date)
    """)
    db.commit()


def _infer_doc_type(action, detail):
    text = (action or '') + ' ' + (detail or '')
    rules = [
        ('purchase_order', ('采购单', '采购明细')),
        ('sales_order', ('销售出库', '出库单', '销售明细')),
        ('contract', ('合同',)),
        ('invoice', ('发票',)),
        ('payment', ('付款', '回款')),
        ('transaction', ('交易', '费用', '往来', '入账', 'OCR', 'Excel')),
        ('investment', ('投资',)),
        ('dividend', ('分红',)),
        ('transport', ('运输',)),
        ('reconciliation', ('对账',)),
        ('project', ('项目',)),
        ('participant', ('参与人',)),
        ('collab_recharge', ('充值',)),
        ('collab_deduction', ('扣减',)),
        ('sales_payment', ('销售回款',)),
        ('account', ('账号', '用户', '专员', '权限')),
        ('backup', ('备份',)),
    ]
    for code, kws in rules:
        if any(k in text for k in kws):
            return code
    return 'other'


def _infer_op_type(action, detail):
    action = (action or '').strip()
    detail = (detail or '').strip()
    if '导入' in action or '导入' in detail:
        return 'import'
    if any(k in action for k in ('新增', '创建', '添加')):
        return 'create'
    if any(k in action for k in ('删除',)):
        return 'delete'
    if '反提交' in action:
        return 'unsubmit'
    if '提交' in action:
        return 'submit'
    if any(k in action for k in ('修改', '编辑', '维护', '更新')):
        return 'update'
    if any(k in action for k in ('确认', '审核', '对账', '入账')):
        return 'confirm'
    return 'other'


def _parse_counts(action, detail, op_type):
    """解析单据张数与明细/记录条数。"""
    detail = detail or ''
    action = action or ''
    doc_count = 0
    record_count = 0

    if op_type in ('create', 'import', 'delete', 'submit', 'unsubmit', 'update', 'confirm'):
        doc_count = 1

    for pat in (
        r'(\d+)\s*张',
        r'(\d+)\s*个单据',
        r'共\s*(\d+)\s*个',
        r'批量.*?(\d+)',
        r'(\d+)\s*单',
    ):
        m = re.search(pat, detail + action)
        if m:
            try:
                doc_count = max(doc_count, int(m.group(1)))
            except ValueError:
                pass

    for pat in (
        r'导入\s*(\d+)\s*条',
        r'(\d+)\s*条明细',
        r'共\s*(\d+)\s*条',
        r'(\d+)\s*条记录',
    ):
        m = re.search(pat, detail)
        if m:
            try:
                record_count = max(record_count, int(m.group(1)))
            except ValueError:
                pass

    if op_type == 'import' and record_count > 0 and doc_count < 1:
        doc_count = 1
    if op_type in ('create', 'import') and doc_count < 1 and op_type != 'other':
        doc_count = 1

    return doc_count, record_count


def parse_log_metadata(action, detail=''):
    """完整解析日志元数据。"""
    doc_type = _infer_doc_type(action, detail)
    op_type = _infer_op_type(action, detail)
    doc_count, record_count = _parse_counts(action, detail, op_type)
    feature_module = doc_type if doc_type in MODULE_LABELS else _module_from_doc_type(doc_type)
    if feature_module == 'other':
        feature_module, _ = classify_log_action_legacy(action, detail)
    entity_count = record_count
    if action in ('登录', '登出'):
        doc_count = record_count = 0
        entity_count = 0
    return {
        'feature_module': feature_module,
        'doc_type': doc_type,
        'op_type': op_type,
        'doc_count': doc_count,
        'record_count': record_count,
        'entity_count': entity_count,
    }


def _module_from_doc_type(doc_type):
    mapping = {
        'purchase_order': 'purchase',
        'sales_order': 'sales',
        'sales_payment': 'sales',
        'collab_recharge': 'collab',
        'collab_deduction': 'collab',
    }
    return mapping.get(doc_type, doc_type if doc_type in MODULE_LABELS else 'other')


def classify_log_action(action, detail=''):
    """兼容旧接口：返回 (feature_module, entity_count)。"""
    meta = parse_log_metadata(action, detail)
    return meta['feature_module'], meta['entity_count']


def classify_log_action_legacy(action, detail=''):
    text = (action or '') + ' ' + (detail or '')
    for mod, kws in [
        ('project', ('项目',)), ('purchase', ('采购',)), ('sales', ('销售', '出库')),
        ('contract', ('合同',)), ('invoice', ('发票',)), ('payment', ('付款',)),
        ('transaction', ('交易', '费用',)), ('investment', ('投资',)),
        ('dividend', ('分红',)), ('transport', ('运输',)), ('collab', ('协同', '客户')),
        ('account', ('账号',)), ('backup', ('备份',)), ('auth', ('登录', '登出')),
    ]:
        if any(k in text for k in kws):
            return mod, 0
    return 'other', 0


def record_feature_access(db, user_id, username, endpoint, path):
    if not user_id or not endpoint:
        return
    info = ENDPOINT_FEATURES.get(endpoint)
    if not info:
        return
    feature_key, feature_label = info
    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = db.execute(
        """SELECT id, access_count FROM log_feature_access
           WHERE user_id=? AND feature_key=? AND access_date=?""",
        (user_id, feature_key, today),
    ).fetchone()
    if row:
        db.execute(
            """UPDATE log_feature_access SET access_count=?, last_access_at=?,
               feature_label=?, route_path=?, username=? WHERE id=?""",
            (row['access_count'] + 1, now, feature_label, path, username, row['id']),
        )
    else:
        db.execute(
            """INSERT INTO log_feature_access
               (user_id, username, feature_key, feature_label, route_path,
                access_date, access_count, first_access_at, last_access_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, username, feature_key, feature_label, path, today, now, now),
        )
    db.commit()


def _parse_log_datetime(created_at):
    if not created_at:
        return None
    s = str(created_at)[:19].replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _date_filter_sql(date_from, date_to, view_date):
    if view_date:
        return " AND date(created_at) = ? ", [view_date]
    clauses, params = [], []
    if date_from:
        clauses.append("date(created_at) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date(created_at) <= ?")
        params.append(date_to)
    if not clauses:
        return '', []
    return ' AND ' + ' AND '.join(clauses) + ' ', params


def query_logs(db, date_from=None, date_to=None, view_date=None, username=None,
               action_kw=None, page=1, per_page=50):
    ensure_log_schema(db)
    where, params = ' WHERE 1=1 ', []
    extra, extra_params = _date_filter_sql(date_from, date_to, view_date)
    where += extra
    params.extend(extra_params)
    if username:
        where += ' AND username LIKE ? '
        params.append(f'%{username}%')
    if action_kw:
        where += ' AND (action LIKE ? OR detail LIKE ?) '
        params.extend([f'%{action_kw}%', f'%{action_kw}%'])
    total = db.execute(f'SELECT COUNT(*) FROM logs {where}', params).fetchone()[0]
    rows = db.execute(
        f'SELECT * FROM logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [per_page, (page - 1) * per_page],
    ).fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return rows, total, total_pages


def query_logs_by_day(db, date_from=None, date_to=None, username=None, limit=90):
    ensure_log_schema(db)
    where, params = ' WHERE 1=1 ', []
    extra, extra_params = _date_filter_sql(date_from, date_to, None)
    where += extra
    params.extend(extra_params)
    if username:
        where += ' AND username LIKE ? '
        params.append(f'%{username}%')
    rows = db.execute(
        f"""SELECT date(created_at) AS log_date, COUNT(*) AS op_count,
                   COUNT(DISTINCT username) AS user_count,
                   SUM(COALESCE(entity_count, 0)) AS record_count,
                   SUM(COALESCE(doc_count, 0)) AS doc_count
            FROM logs {where} GROUP BY date(created_at)
            ORDER BY log_date DESC LIMIT ?""",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def delete_logs_in_range(db, date_from, date_to, delete_access=True):
    if not date_from or not date_to:
        return 0, 0, '请填写开始和结束日期'
    try:
        d0 = datetime.strptime(date_from, '%Y-%m-%d').date()
        d1 = datetime.strptime(date_to, '%Y-%m-%d').date()
    except ValueError:
        return 0, 0, '日期格式无效'
    if d0 > d1:
        return 0, 0, '开始日期不能晚于结束日期'
    ensure_log_schema(db)
    n_logs = db.execute(
        "SELECT COUNT(*) FROM logs WHERE date(created_at) BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchone()[0]
    db.execute("DELETE FROM logs WHERE date(created_at) BETWEEN ? AND ?", (date_from, date_to))
    n_access = 0
    if delete_access:
        n_access = db.execute(
            "SELECT COUNT(*) FROM log_feature_access WHERE access_date BETWEEN ? AND ?",
            (date_from, date_to),
        ).fetchone()[0]
        db.execute(
            "DELETE FROM log_feature_access WHERE access_date BETWEEN ? AND ?",
            (date_from, date_to),
        )
    db.commit()
    return n_logs, n_access, None


def _row_metadata(row):
    """从日志行取元数据，必要时回退解析。"""
    action = row['action'] or ''
    detail = row['detail'] or ''
    keys = row.keys() if hasattr(row, 'keys') else []
    if 'doc_type' in keys and row['doc_type'] and 'op_type' in keys and row['op_type']:
        return {
            'doc_type': row['doc_type'],
            'op_type': row['op_type'],
            'doc_count': int(row['doc_count'] or 0),
            'record_count': int(row['entity_count'] or 0),
            'feature_module': row['feature_module'] or _module_from_doc_type(row['doc_type']),
        }
    return parse_log_metadata(action, detail)


def _format_doc_breakdown(counter_dict):
    """counter_dict: doc_type -> {doc_count, record_count}"""
    items = []
    for doc_type, vals in sorted(counter_dict.items(), key=lambda x: -x[1]['doc_count']):
        if vals['doc_count'] <= 0 and vals['record_count'] <= 0:
            continue
        items.append({
            'doc_type': doc_type,
            'label': DOC_TYPE_LABELS.get(doc_type, doc_type),
            'doc_count': vals['doc_count'],
            'record_count': vals['record_count'],
        })
    return items


def build_user_analytics(db, date_from=None, date_to=None):
    ensure_log_schema(db)
    extra, params = _date_filter_sql(date_from, date_to, None)
    where_logs = ' WHERE 1=1 ' + extra

    log_rows = db.execute(
        f"""SELECT username, user_id, action, detail, feature_module,
                   doc_type, op_type, doc_count, entity_count, created_at
            FROM logs {where_logs}""",
        params,
    ).fetchall()

    access_extra, access_params = '', []
    if date_from:
        access_extra += ' AND access_date >= ? '
        access_params.append(date_from)
    if date_to:
        access_extra += ' AND access_date <= ? '
        access_params.append(date_to)
    access_rows = db.execute(
        f"""SELECT username, user_id, feature_key, feature_label, SUM(access_count) AS clicks
            FROM log_feature_access WHERE 1=1 {access_extra}
            GROUP BY username, user_id, feature_key""",
        access_params,
    ).fetchall()

    users = defaultdict(lambda: {
        'username': '', 'user_id': None, 'op_count': 0,
        'feature_types': set(), 'action_types': set(),
        'doc_op_count': 0, 'record_count': 0, 'doc_count_total': 0,
        'hour_counter': Counter(), 'action_counter': Counter(),
        'module_counter': Counter(), 'feature_clicks': 0,
        'feature_click_types': set(), 'top_features': Counter(),
        'create_by_doc': defaultdict(lambda: {'doc_count': 0, 'record_count': 0}),
        'import_by_doc': defaultdict(lambda: {'doc_count': 0, 'record_count': 0}),
        'all_create_by_doc': defaultdict(lambda: {'doc_count': 0, 'record_count': 0}),
        'daily_ops': Counter(),
        'op_by_type': Counter(),
    })

    for row in log_rows:
        uname = row['username'] or '（未知）'
        u = users[uname]
        u['username'] = uname
        u['user_id'] = row['user_id']
        u['op_count'] += 1
        action = row['action'] or ''
        u['action_types'].add(action)
        u['action_counter'][action] += 1

        meta = _row_metadata(row)
        mod = meta['feature_module']
        u['feature_types'].add(mod)
        u['module_counter'][mod] += 1
        u['record_count'] += meta['record_count']
        u['doc_count_total'] += meta['doc_count']
        u['op_by_type'][meta['op_type']] += 1

        if any(k in action for k in DOC_ACTION_KEYWORDS):
            u['doc_op_count'] += 1

        dt = _parse_log_datetime(row['created_at'])
        if dt:
            u['hour_counter'][dt.hour] += 1
            u['daily_ops'][dt.strftime('%Y-%m-%d')] += 1

        if meta['op_type'] in ('create', 'import'):
            bucket = u['create_by_doc'] if meta['op_type'] == 'create' else u['import_by_doc']
            bucket[meta['doc_type']]['doc_count'] += meta['doc_count']
            bucket[meta['doc_type']]['record_count'] += meta['record_count']
            u['all_create_by_doc'][meta['doc_type']]['doc_count'] += meta['doc_count']
            u['all_create_by_doc'][meta['doc_type']]['record_count'] += meta['record_count']

    for row in access_rows:
        uname = row['username'] or '（未知）'
        u = users[uname]
        u['feature_clicks'] += int(row['clicks'] or 0)
        u['feature_click_types'].add(row['feature_key'])
        u['top_features'][row['feature_label'] or row['feature_key']] += int(row['clicks'] or 0)

    result = []
    for uname, u in users.items():
        create_items = _format_doc_breakdown(u['create_by_doc'])
        import_items = _format_doc_breakdown(u['import_by_doc'])
        all_new_items = _format_doc_breakdown(u['all_create_by_doc'])
        new_doc_summary = '；'.join(
            f"{x['label']} {x['doc_count']}张" + (f"/{x['record_count']}条" if x['record_count'] else '')
            for x in all_new_items[:8]
        ) or '—'

        result.append({
            'username': uname,
            'user_id': u['user_id'],
            'op_count': u['op_count'],
            'feature_type_count': len(u['feature_types']),
            'action_type_count': len(u['action_types']),
            'feature_click_count': u['feature_clicks'],
            'feature_nav_count': len(u['feature_click_types']),
            'doc_op_count': u['doc_op_count'],
            'record_count': u['record_count'],
            'doc_count_total': u['doc_count_total'],
            'new_doc_count': sum(x['doc_count'] for x in all_new_items),
            'new_record_count': sum(x['record_count'] for x in all_new_items),
            'new_doc_summary': new_doc_summary,
            'create_breakdown': create_items,
            'import_breakdown': import_items,
            'all_new_breakdown': all_new_items,
            'peak_hours': _format_peak_hours(u['hour_counter']),
            'top_actions': '、'.join(a for a, _ in u['action_counter'].most_common(3)) or '—',
            'top_modules': '、'.join(MODULE_LABELS.get(m, m) for m, _ in u['module_counter'].most_common(3)) or '—',
            'top_feature_nav': '、'.join(f for f, _ in u['top_features'].most_common(3)) or '—',
            'daily_labels': sorted(u['daily_ops'].keys()),
            'daily_values': [u['daily_ops'][d] for d in sorted(u['daily_ops'].keys())],
            'hour_labels': [f'{h:02d}:00' for h in range(24)],
            'hour_values': [u['hour_counter'].get(h, 0) for h in range(24)],
            'create_chart_labels': [x['label'] for x in create_items],
            'create_chart_docs': [x['doc_count'] for x in create_items],
            'create_chart_records': [x['record_count'] for x in create_items],
            'feature_chart_labels': [f for f, _ in u['top_features'].most_common(8)],
            'feature_chart_values': [c for _, c in u['top_features'].most_common(8)],
            'op_type_labels': [OP_TYPE_LABELS.get(k, k) for k, _ in u['op_by_type'].most_common(6)],
            'op_type_values': [c for _, c in u['op_by_type'].most_common(6)],
        })

    result.sort(key=lambda x: (-x['op_count'], x['username']))
    return result


def build_analytics_chart_payload(users, date_from, date_to):
    """全局图表数据（汇总所有用户）。"""
    user_labels = [u['username'] for u in users[:15]]
    user_ops = [u['op_count'] for u in users[:15]]
    user_new_docs = [u['new_doc_count'] for u in users[:15]]
    user_new_records = [u['new_record_count'] for u in users[:15]]

    doc_totals = defaultdict(lambda: {'doc_count': 0, 'record_count': 0})
    for u in users:
        for item in u.get('all_new_breakdown', []):
            doc_totals[item['doc_type']]['doc_count'] += item['doc_count']
            doc_totals[item['doc_type']]['record_count'] += item['record_count']
    doc_items = _format_doc_breakdown(doc_totals)

    return {
        'date_from': date_from,
        'date_to': date_to,
        'user_labels': user_labels,
        'user_ops': user_ops,
        'user_new_docs': user_new_docs,
        'user_new_records': user_new_records,
        'doc_labels': [x['label'] for x in doc_items],
        'doc_counts': [x['doc_count'] for x in doc_items],
        'record_counts': [x['record_count'] for x in doc_items],
        'users': users,
    }


def analytics_chart_json(users, date_from, date_to):
    return json.dumps(build_analytics_chart_payload(users, date_from, date_to), ensure_ascii=False)


def _format_peak_hours(hour_counter, top_n=2):
    if not hour_counter:
        return '—'
    return '；'.join(
        f'{h:02d}:00-{(h + 1) % 24:02d}:00({c}次)'
        for h, c in hour_counter.most_common(top_n)
    )


def backfill_log_metadata(db, batch_size=5000):
    ensure_log_schema(db)
    rows = db.execute(
        """SELECT id, action, detail FROM logs
           WHERE doc_type IS NULL OR doc_type = '' OR feature_module IS NULL OR feature_module = ''
           LIMIT ?""",
        (batch_size,),
    ).fetchall()
    for row in rows:
        meta = parse_log_metadata(row['action'], row['detail'])
        db.execute(
            """UPDATE logs SET feature_module=?, entity_count=?, doc_type=?, op_type=?, doc_count=?
               WHERE id=?""",
            (meta['feature_module'], meta['record_count'], meta['doc_type'],
             meta['op_type'], meta['doc_count'], row['id']),
        )
    db.commit()
    return len(rows)
