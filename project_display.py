# -*- coding: utf-8 -*-
"""
业务单据与项目的关系：仅存 project_id，不冗余项目名称。
展示、列表、报表、API 通过 JOIN projects 读取当前名称，管理员改名后各处自动同步。
"""

# 应只含 project_id、不含 project_name 列的业务表（用于启动时巡检）
TABLES_PROJECT_ID_ONLY = (
    'transaction_records',
    'invoices',
    'purchase_orders',
    'sales_orders',
    'contracts',
    'transport_records',
    'payments',
    'investments',
    'dividends',
    'reconciliations',
)


def project_join_sql(table_alias, project_alias='p', fk_col='project_id'):
    return (
        f'LEFT JOIN projects {project_alias} '
        f'ON {table_alias}.{fk_col} = {project_alias}.id'
    )


def project_name_expr(project_alias='p'):
    return f'{project_alias}.name AS project_name'


def fetch_purchase_by_id(db, purchase_id, with_contract=True):
    contract_sel = ', c.contract_name' if with_contract else ''
    contract_join = (
        'LEFT JOIN contracts c ON po.contract_id = c.id' if with_contract else ''
    )
    return db.execute(
        f"""SELECT po.*, {project_name_expr('p')}{contract_sel}
            FROM purchase_orders po
            {project_join_sql('po')}
            {contract_join}
            WHERE po.id = ?""",
        (purchase_id,),
    ).fetchone()


def fetch_sales_order_by_id(db, order_id, with_contract=True):
    contract_sel = ', c.contract_name' if with_contract else ''
    contract_join = (
        'LEFT JOIN contracts c ON so.contract_id = c.id' if with_contract else ''
    )
    return db.execute(
        f"""SELECT so.*, {project_name_expr('p')}{contract_sel}
            FROM sales_orders so
            {project_join_sql('so')}
            {contract_join}
            WHERE so.id = ?""",
        (order_id,),
    ).fetchone()


def fetch_contract_by_id(db, contract_id):
    return db.execute(
        f"""SELECT c.*, {project_name_expr('p')}
            FROM contracts c
            {project_join_sql('c')}
            WHERE c.id = ?""",
        (contract_id,),
    ).fetchone()


def fetch_invoice_by_id(db, invoice_id):
    return db.execute(
        f"""SELECT i.*, {project_name_expr('p')},
                   c.contract_name
            FROM invoices i
            {project_join_sql('i')}
            LEFT JOIN contracts c ON i.contract_id = c.id
            WHERE i.id = ?""",
        (invoice_id,),
    ).fetchone()


def fetch_transaction_by_id(db, trans_id):
    return db.execute(
        f"""SELECT t.*, {project_name_expr('p')},
                   par.name AS participant_name,
                   cat.name AS category_name
            FROM transaction_records t
            {project_join_sql('t')}
            LEFT JOIN participants par ON t.participant_id = par.id
            LEFT JOIN categories cat ON t.category_id = cat.id
            WHERE t.id = ?""",
        (trans_id,),
    ).fetchone()


def list_tables_with_redundant_project_name(db):
    """返回误含 project_name 列的表名（历史脏数据）。"""
    bad = []
    for table in TABLES_PROJECT_ID_ONLY:
        try:
            cols = {r[1] for r in db.execute(
                f'PRAGMA table_info({table})'
            ).fetchall()}
        except Exception:
            continue
        if 'project_name' in cols:
            bad.append(table)
    return bad


def ensure_project_display_schema(db):
    """启动时巡检：单据表不应冗余 project_name。"""
    redundant = list_tables_with_redundant_project_name(db)
    if redundant:
        import logging
        logging.getLogger(__name__).warning(
            '以下表含冗余列 project_name，展示请用 project_id JOIN projects：%s',
            ', '.join(redundant),
        )
