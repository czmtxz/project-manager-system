#!/usr/bin/env python3
"""
迭代1：数据库重构 - 用户注册、审批流程、权限管理
"""
import sqlite3
import os
import hashlib

db_path = r'c:\Users\陈志明\.trae-cn\work\6a01570a6e57f680d6352115\project_manager\project_manager.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=== 迭代1：数据库重构 ===")

# 1. 备份并重建users表（增加新字段）
print("1. 重构users表...")
cursor.execute("ALTER TABLE users RENAME TO users_old")
cursor.execute('''
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        real_name TEXT,
        phone TEXT,
        email TEXT,
        department TEXT,
        role TEXT DEFAULT 'user',
        status TEXT DEFAULT 'pending',
        created_by INTEGER,
        approved_by INTEGER,
        approved_at TIMESTAMP,
        last_login TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id),
        FOREIGN KEY (approved_by) REFERENCES users(id)
    )
''')

# 迁移旧用户数据
cursor.execute('''
    INSERT INTO users (id, username, password, role, status, created_at)
    SELECT id, username, password, role, 'active', created_at FROM users_old
''')
cursor.execute("DROP TABLE users_old")
print("   users表重构完成")

# 2. 创建角色权限表
print("2. 创建角色权限表...")
cursor.execute('''
    CREATE TABLE roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        is_system INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 初始化系统角色
cursor.executemany('''
    INSERT INTO roles (code, name, description, is_system) VALUES (?, ?, ?, 1)
''', [
    ('admin', '系统管理员', '拥有所有权限'),
    ('finance', '财务主管', '管理财务数据、审批'),
    ('manager', '项目经理', '管理项目、查看报表'),
    ('user', '普通用户', '录入数据、查看自己相关数据'),
])
print("   角色表创建完成")

# 3. 创建权限定义表
print("3. 创建权限定义表...")
cursor.execute('''
    CREATE TABLE permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        description TEXT
    )
''')

# 初始化权限定义
permissions = [
    # 用户管理
    ('user_view', '查看用户', 'user', 'view', '查看用户列表'),
    ('user_create', '创建用户', 'user', 'create', '创建新用户'),
    ('user_edit', '编辑用户', 'user', 'edit', '编辑用户信息'),
    ('user_delete', '删除用户', 'user', 'delete', '删除用户'),
    ('user_approve', '审批用户', 'user', 'approve', '审批注册用户'),
    # 项目管理
    ('project_view_all', '查看所有项目', 'project', 'view_all', '查看所有项目'),
    ('project_view_own', '查看自己的项目', 'project', 'view_own', '查看自己参与的项目'),
    ('project_create', '创建项目', 'project', 'create', '创建新项目'),
    ('project_edit', '编辑项目', 'project', 'edit', '编辑项目信息'),
    ('project_delete', '删除项目', 'project', 'delete', '删除项目'),
    # 交易记录
    ('transaction_view', '查看交易', 'transaction', 'view', '查看交易记录'),
    ('transaction_create', '创建交易', 'transaction', 'create', '创建交易记录'),
    ('transaction_edit', '编辑交易', 'transaction', 'edit', '编辑交易记录'),
    ('transaction_delete', '删除交易', 'transaction', 'delete', '删除交易记录'),
    ('transaction_approve', '审批交易', 'transaction', 'approve', '审批交易记录'),
    # 分类管理
    ('category_view', '查看分类', 'category', 'view', '查看分类'),
    ('category_manage', '管理分类', 'category', 'manage', '管理分类'),
    # 报表
    ('report_view', '查看报表', 'report', 'view', '查看报表'),
    ('report_export', '导出报表', 'report', 'export', '导出报表'),
    # 系统管理
    ('system_backup', '系统备份', 'system', 'backup', '系统备份'),
    ('system_config', '系统配置', 'system', 'config', '系统配置'),
]
cursor.executemany('INSERT INTO permissions (code, name, module, action, description) VALUES (?,?,?,?,?)', permissions)
print("   权限表创建完成")

# 4. 创建角色-权限关联表
print("4. 创建角色-权限关联表...")
cursor.execute('''
    CREATE TABLE role_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_code TEXT NOT NULL,
        permission_code TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(role_code, permission_code)
    )
''')

# 初始化角色权限
role_permissions = [
    # admin拥有所有权限
    ('admin', 'user_view'), ('admin', 'user_create'), ('admin', 'user_edit'), ('admin', 'user_delete'), ('admin', 'user_approve'),
    ('admin', 'project_view_all'), ('admin', 'project_create'), ('admin', 'project_edit'), ('admin', 'project_delete'),
    ('admin', 'transaction_view'), ('admin', 'transaction_create'), ('admin', 'transaction_edit'), ('admin', 'transaction_delete'), ('admin', 'transaction_approve'),
    ('admin', 'category_view'), ('admin', 'category_manage'),
    ('admin', 'report_view'), ('admin', 'report_export'),
    ('admin', 'system_backup'), ('admin', 'system_config'),
    # finance权限
    ('finance', 'project_view_all'), ('finance', 'transaction_view'), ('finance', 'transaction_create'), ('finance', 'transaction_approve'),
    ('finance', 'category_view'), ('finance', 'report_view'), ('finance', 'report_export'),
    # manager权限
    ('manager', 'project_view_all'), ('manager', 'project_create'), ('manager', 'project_edit'),
    ('manager', 'transaction_view'), ('manager', 'transaction_create'), ('manager', 'transaction_edit'),
    ('manager', 'category_view'), ('manager', 'report_view'),
    # user权限
    ('user', 'project_view_own'), ('user', 'transaction_view'), ('user', 'transaction_create'),
]
cursor.executemany('INSERT INTO role_permissions (role_code, permission_code) VALUES (?,?)', role_permissions)
print("   角色权限关联完成")

# 5. 创建审批流程定义表
print("5. 创建审批流程表...")
cursor.execute('''
    CREATE TABLE approval_workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        description TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 初始化审批流程
cursor.executemany('''
    INSERT INTO approval_workflows (name, entity_type, description) VALUES (?, ?, ?)
''', [
    ('交易记录审批', 'transaction', '交易记录提交后的审批流程'),
    ('用户注册审批', 'user_registration', '新用户注册的审批流程'),
])
print("   审批流程表创建完成")

# 6. 创建审批步骤表
print("6. 创建审批步骤表...")
cursor.execute('''
    CREATE TABLE approval_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id INTEGER NOT NULL,
        step_order INTEGER NOT NULL,
        step_name TEXT NOT NULL,
        approver_role TEXT,
        approver_user_id INTEGER,
        is_parallel INTEGER DEFAULT 0,
        FOREIGN KEY (workflow_id) REFERENCES approval_workflows(id),
        FOREIGN KEY (approver_user_id) REFERENCES users(id)
    )
''')

# 初始化审批步骤
cursor.execute("SELECT id FROM approval_workflows WHERE entity_type='transaction'")
tx_workflow_id = cursor.fetchone()[0]
cursor.executemany('''
    INSERT INTO approval_steps (workflow_id, step_order, step_name, approver_role) VALUES (?, ?, ?, ?)
''', [
    (tx_workflow_id, 1, '项目经理审批', 'manager'),
    (tx_workflow_id, 2, '财务审批', 'finance'),
])

cursor.execute("SELECT id FROM approval_workflows WHERE entity_type='user_registration'")
user_workflow_id = cursor.fetchone()[0]
cursor.execute('''
    INSERT INTO approval_steps (workflow_id, step_order, step_name, approver_role) VALUES (?, ?, ?, ?)
''', (user_workflow_id, 1, '管理员审批', 'admin'))
print("   审批步骤表创建完成")

# 7. 创建审批记录表
print("7. 创建审批记录表...")
cursor.execute('''
    CREATE TABLE approval_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id INTEGER NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        current_step INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        submitted_by INTEGER,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (workflow_id) REFERENCES approval_workflows(id),
        FOREIGN KEY (submitted_by) REFERENCES users(id)
    )
''')
print("   审批记录表创建完成")

# 8. 创建审批历史表
print("8. 创建审批历史表...")
cursor.execute('''
    CREATE TABLE approval_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        step_id INTEGER,
        approver_id INTEGER,
        action TEXT NOT NULL,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (record_id) REFERENCES approval_records(id),
        FOREIGN KEY (step_id) REFERENCES approval_steps(id),
        FOREIGN KEY (approver_id) REFERENCES users(id)
    )
''')
print("   审批历史表创建完成")

# 9. 创建用户-分类权限表（用于控制用户可见的分类范围）
print("9. 创建用户-分类权限表...")
cursor.execute('''
    CREATE TABLE user_category_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category_id INTEGER NOT NULL,
        can_view INTEGER DEFAULT 1,
        can_create INTEGER DEFAULT 0,
        can_edit INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (category_id) REFERENCES categories(id),
        UNIQUE(user_id, category_id)
    )
''')
print("   用户分类权限表创建完成")

# 10. 更新transaction_records表，增加审批状态字段
print("10. 更新transaction_records表...")
cursor.execute("ALTER TABLE transaction_records ADD COLUMN approval_status TEXT DEFAULT 'draft'")
cursor.execute("ALTER TABLE transaction_records ADD COLUMN approval_record_id INTEGER")
print("   交易记录表更新完成")

conn.commit()

# 统计
print("\n=== 数据库重构完成 ===")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print(f"现有表: {len(tables)} 个")
print(f"  {', '.join(sorted(tables))}")

conn.close()
print("\n迭代1数据库重构完成！")
