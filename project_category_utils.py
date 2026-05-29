# -*- coding: utf-8 -*-
"""项目费用分类白名单：基础资料为标准库，各项目仅启用部分分类"""


def ensure_project_categories_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS project_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
            UNIQUE(project_id, category_id)
        )
    """)


def project_uses_category_whitelist(db, project_id):
    row = db.execute(
        "SELECT 1 FROM project_categories WHERE project_id=? LIMIT 1",
        (project_id,),
    ).fetchone()
    return row is not None


def get_project_enabled_category_ids(db, project_id):
    rows = db.execute(
        "SELECT category_id FROM project_categories WHERE project_id=? ORDER BY category_id",
        (project_id,),
    ).fetchall()
    return [r["category_id"] for r in rows]


def leaf_category_clause(alias="c"):
    """SQL：仅最末级科目（不存在以该节点为 parent 的子科目）。"""
    return (
        f" AND NOT EXISTS (SELECT 1 FROM categories _ch WHERE _ch.parent_id = {alias}.id)"
    )


def is_leaf_category(db, category_id):
    if not category_id:
        return False
    row = db.execute(
        "SELECT 1 FROM categories WHERE parent_id=? LIMIT 1",
        (int(category_id),),
    ).fetchone()
    return row is None


def fetch_leaf_categories(db, trans_type=None):
    q = """
        SELECT * FROM categories c
        WHERE NOT EXISTS (SELECT 1 FROM categories ch WHERE ch.parent_id = c.id)
    """
    params = []
    if trans_type:
        q += " AND c.type=?"
        params.append(trans_type)
    q += " ORDER BY c.type, COALESCE(c.sort_order, 0), c.code, c.name"
    return db.execute(q, params).fetchall()


def get_category_full_name(db, category_id):
    parts = []
    cid = category_id
    seen = set()
    while cid and cid not in seen:
        seen.add(cid)
        row = db.execute(
            "SELECT id, parent_id, name FROM categories WHERE id=?", (cid,)
        ).fetchone()
        if not row:
            break
        parts.append(row["name"])
        cid = row["parent_id"]
    return " / ".join(reversed(parts)) if parts else ""


def get_project_categories_list(db, project_id, trans_type=None):
    """项目可用分类；已配置白名单时仅返回启用项，未配置时返回全部（兼容旧数据）。"""
    if project_uses_category_whitelist(db, project_id):
        ids = get_project_enabled_category_ids(db, project_id)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        q = f"SELECT * FROM categories WHERE id IN ({placeholders})"
        params = list(ids)
    else:
        q = "SELECT * FROM categories WHERE 1=1"
        params = []

    if trans_type:
        q += " AND type=?"
        params.append(trans_type)
    q += leaf_category_clause("categories")
    q += " ORDER BY type, COALESCE(sort_order, 0), code, name"
    return db.execute(q, params).fetchall()


def get_grouped_categories_json(db, project_id):
    cats = get_project_categories_list(db, project_id)
    income, expense = [], []
    for c in cats:
        item = {
            "id": c["id"],
            "code": (c["code"] or "") if "code" in c.keys() else "",
            "name": c["name"],
            "full_name": get_category_full_name(db, c["id"]),
            "type": c["type"],
            "level": (c["level"] or 1) if "level" in c.keys() else 1,
        }
        (income if c["type"] == "income" else expense).append(item)
    return {"income": income, "expense": expense}


def set_project_categories(db, project_id, category_ids):
    db.execute("DELETE FROM project_categories WHERE project_id=?", (project_id,))
    for cid in category_ids:
        if cid and is_leaf_category(db, cid):
            db.execute(
                "INSERT OR IGNORE INTO project_categories (project_id, category_id) VALUES (?, ?)",
                (project_id, int(cid)),
            )


def validate_project_category(db, project_id, category_id):
    if not category_id:
        return True
    category_id = int(category_id)
    if not is_leaf_category(db, category_id):
        return False
    if not project_uses_category_whitelist(db, project_id):
        return (
            db.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone()
            is not None
        )
    return (
        db.execute(
            "SELECT 1 FROM project_categories WHERE project_id=? AND category_id=?",
            (project_id, category_id),
        ).fetchone()
        is not None
    )


def category_ids_sql_filter(db, project_id, column="c.id"):
    """返回 (sql_fragment, params)。未配置白名单时不追加条件。"""
    if not project_uses_category_whitelist(db, project_id):
        return "", []
    ids = get_project_enabled_category_ids(db, project_id)
    if not ids:
        return f" AND 1=0", []
    placeholders = ",".join("?" * len(ids))
    return f" AND {column} IN ({placeholders})", list(ids)
