# -*- coding: utf-8 -*-
"""备份库只读预览与按项目引入业务数据。"""

import sqlite3

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
    if _table_exists(conn, 'projects'):
        for r in conn.execute(
            'SELECT id, name, status FROM projects ORDER BY id'
        ).fetchall():
            pid = r['id']
            summary = _preview_one_project(conn, pid)
            projects.append({
                'id': pid,
                'name': r['name'],
                'status': r['status'],
                'counts': summary.get('counts', []),
                'total_rows': summary.get('total_rows', 0),
            })
    return {
        'mode': 'file',
        'project_count': len(projects),
        'projects': projects[:50],
        'truncated': len(projects) > 50,
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

    counts = []
    total = 0
    for label, table, where in PROJECT_PREVIEW_QUERIES:
        n = _safe_count(conn, table, where, (project_id,))
        if n is None:
            continue
        counts.append({'label': label, 'table': table, 'count': n})
        total += n

    # 采购明细、销售明细
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

    return {
        'mode': 'project',
        'project': dict(project),
        'counts': counts,
        'total_rows': total,
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

    # 挂采购单但 project_id 为空的运输
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
                    pass  # 明细 ID 未全局映射，保留原 ID 可能无效；跳过或按 purchase 重链
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
