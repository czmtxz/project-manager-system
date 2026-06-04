# -*- coding: utf-8 -*-
"""操作日志筛选、按天汇总、用户行为分析、功能访问统计。"""

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

DOC_ACTION_KEYWORDS = (
    '新增', '修改', '删除', '编辑', '提交', '反提交', '导入', '确认', '审核',
    '对账', '入账', '同步', '批量',
)


def ensure_log_schema(db):
    """扩展 logs 表并创建功能访问统计表。"""
    cols = {r[1] for r in db.execute('PRAGMA table_info(logs)').fetchall()}
    if 'feature_module' not in cols:
        db.execute('ALTER TABLE logs ADD COLUMN feature_module TEXT')
    if 'entity_count' not in cols:
        db.execute('ALTER TABLE logs ADD COLUMN entity_count INTEGER DEFAULT 1')
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
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_username ON logs(username)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_feature_access_date
        ON log_feature_access(access_date)
    """)
    db.commit()


def classify_log_action(action, detail=''):
    """根据操作类型与详情推断功能模块与影响条数。"""
    action = (action or '').strip()
    detail = (detail or '').strip()
    text = action + ' ' + detail

    module = 'other'
    rules = [
        ('project', ('项目',)),
        ('purchase', ('采购',)),
        ('sales', ('销售', '出库')),
        ('contract', ('合同',)),
        ('invoice', ('发票',)),
        ('payment', ('付款', '充值', '回款')),
        ('transaction', ('交易', '费用', '往来', '入账', 'OCR', 'Excel')),
        ('investment', ('投资',)),
        ('dividend', ('分红',)),
        ('transport', ('运输',)),
        ('reconciliation', ('对账',)),
        ('report', ('报表', '导出数据')),
        ('collab', ('协同', '客户', '专员', '扣减')),
        ('account', ('账号', '用户', '权限')),
        ('backup', ('备份',)),
        ('auth', ('登录', '登出', '注册')),
        ('system', ('清空',)),
    ]
    for mod, kws in rules:
        if any(k in text for k in kws):
            module = mod
            break

    entity_count = 0
    if action in ('登录', '登出'):
        entity_count = 0
    elif any(k in action for k in DOC_ACTION_KEYWORDS) or '导入' in detail:
        entity_count = 1
        for pat in (
            r'导入\s*(\d+)\s*条',
            r'共\s*(\d+)\s*条',
            r'(\d+)\s*条明细',
            r'批量.*?(\d+)',
            r'(\d+)\s*个',
        ):
            m = re.search(pat, detail)
            if m:
                try:
                    entity_count = max(entity_count, int(m.group(1)))
                except ValueError:
                    pass
        if '批量' in action or '批量' in detail:
            m = re.search(r'(\d+)', detail)
            if m:
                try:
                    entity_count = max(entity_count, int(m.group(1)))
                except ValueError:
                    pass

    return module, entity_count


def record_feature_access(db, user_id, username, endpoint, path):
    """记录员工访问系统功能（按天累计点击次数）。"""
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
               feature_label=?, route_path=?, username=?
               WHERE id=?""",
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
    """返回 (where_clause, params)。"""
    if view_date:
        return " AND date(created_at) = ? ", [view_date]
    clauses = []
    params = []
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
    where = ' WHERE 1=1 '
    params = []
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
    offset = (page - 1) * per_page
    rows = db.execute(
        f'SELECT * FROM logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [per_page, offset],
    ).fetchall()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return rows, total, total_pages


def query_logs_by_day(db, date_from=None, date_to=None, username=None, limit=90):
    ensure_log_schema(db)
    where = ' WHERE 1=1 '
    params = []
    extra, extra_params = _date_filter_sql(date_from, date_to, None)
    where += extra
    params.extend(extra_params)
    if username:
        where += ' AND username LIKE ? '
        params.append(f'%{username}%')

    rows = db.execute(
        f"""SELECT date(created_at) AS log_date,
                   COUNT(*) AS op_count,
                   COUNT(DISTINCT username) AS user_count,
                   SUM(COALESCE(entity_count, 0)) AS record_count
            FROM logs {where}
            GROUP BY date(created_at)
            ORDER BY log_date DESC
            LIMIT ?""",
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
        """SELECT COUNT(*) FROM logs
           WHERE date(created_at) >= ? AND date(created_at) <= ?""",
        (date_from, date_to),
    ).fetchone()[0]
    db.execute(
        """DELETE FROM logs
           WHERE date(created_at) >= ? AND date(created_at) <= ?""",
        (date_from, date_to),
    )
    n_access = 0
    if delete_access:
        n_access = db.execute(
            """SELECT COUNT(*) FROM log_feature_access
               WHERE access_date >= ? AND access_date <= ?""",
            (date_from, date_to),
        ).fetchone()[0]
        db.execute(
            """DELETE FROM log_feature_access
               WHERE access_date >= ? AND access_date <= ?""",
            (date_from, date_to),
        )
    db.commit()
    return n_logs, n_access, None


def build_user_analytics(db, date_from=None, date_to=None):
    """按用户汇总操作与功能访问统计。"""
    ensure_log_schema(db)
    extra, params = _date_filter_sql(date_from, date_to, None)
    where_logs = ' WHERE 1=1 ' + extra

    log_rows = db.execute(
        f"""SELECT username, user_id, action, detail, feature_module,
                   COALESCE(entity_count, 0) AS entity_count, created_at
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
        f"""SELECT username, user_id, feature_key, feature_label,
                   SUM(access_count) AS clicks
            FROM log_feature_access WHERE 1=1 {access_extra}
            GROUP BY username, user_id, feature_key""",
        access_params,
    ).fetchall()

    users = defaultdict(lambda: {
        'username': '',
        'user_id': None,
        'op_count': 0,
        'feature_types': set(),
        'action_types': set(),
        'doc_op_count': 0,
        'record_count': 0,
        'hour_counter': Counter(),
        'action_counter': Counter(),
        'module_counter': Counter(),
        'feature_clicks': 0,
        'feature_click_types': set(),
        'top_features': Counter(),
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

        mod = row['feature_module'] or classify_log_action(action, row['detail'])[0]
        u['feature_types'].add(mod)
        u['module_counter'][mod] += 1

        ec = row['entity_count'] or 0
        if ec == 0 and action not in ('登录', '登出'):
            _, ec = classify_log_action(action, row['detail'])
        u['record_count'] += ec

        if any(k in action for k in DOC_ACTION_KEYWORDS):
            u['doc_op_count'] += 1

        dt = _parse_log_datetime(row['created_at'])
        if dt:
            u['hour_counter'][dt.hour] += 1

    for row in access_rows:
        uname = row['username'] or '（未知）'
        u = users[uname]
        u['username'] = uname
        u['user_id'] = row['user_id']
        clicks = int(row['clicks'] or 0)
        u['feature_clicks'] += clicks
        u['feature_click_types'].add(row['feature_key'])
        label = row['feature_label'] or row['feature_key']
        u['top_features'][label] += clicks

    result = []
    for uname, u in users.items():
        peak_hours = _format_peak_hours(u['hour_counter'])
        top_actions = '、'.join(a for a, _ in u['action_counter'].most_common(3))
        top_modules = '、'.join(
            MODULE_LABELS.get(m, m) for m, _ in u['module_counter'].most_common(3)
        )
        top_feature_nav = '、'.join(f for f, _ in u['top_features'].most_common(3))
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
            'peak_hours': peak_hours,
            'top_actions': top_actions or '—',
            'top_modules': top_modules or '—',
            'top_feature_nav': top_feature_nav or '—',
        })

    result.sort(key=lambda x: (-x['op_count'], x['username']))
    return result


def _format_peak_hours(hour_counter, top_n=2):
    if not hour_counter:
        return '—'
    segments = []
    for hour, cnt in hour_counter.most_common(top_n):
        end = (hour + 1) % 24
        segments.append(f'{hour:02d}:00-{end:02d}:00({cnt}次)')
    return '；'.join(segments)


def backfill_log_metadata(db, batch_size=5000):
    """为历史日志补全 feature_module / entity_count（可选维护任务）。"""
    ensure_log_schema(db)
    rows = db.execute(
        """SELECT id, action, detail FROM logs
           WHERE feature_module IS NULL OR feature_module = ''
           LIMIT ?""",
        (batch_size,),
    ).fetchall()
    for row in rows:
        mod, ec = classify_log_action(row['action'], row['detail'])
        db.execute(
            'UPDATE logs SET feature_module=?, entity_count=? WHERE id=?',
            (mod, ec, row['id']),
        )
    db.commit()
    return len(rows)
