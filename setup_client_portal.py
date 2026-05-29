#!/usr/bin/env python3
import sqlite3

DB = '/opt/project_manager/project_manager/project_manager.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. 客户协同账户表
print('=== 创建客户协同账户表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS client_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        contact_name TEXT,
        company_name TEXT,
        status TEXT DEFAULT 'pending',
        balance REAL DEFAULT 0,
        total_recharge REAL DEFAULT 0,
        total_deduct REAL DEFAULT 0,
        alert_threshold REAL DEFAULT 0.1,
        last_alert_at TIMESTAMP,
        approved_by INTEGER,
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (approved_by) REFERENCES users(id)
    )
''')
conn.commit()
print('✅ client_accounts 表创建成功')

# 2. 储值充值记录表
print('\n=== 创建储值充值记录表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS client_recharges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT,
        payment_no TEXT,
        remark TEXT,
        attachment TEXT,
        status TEXT DEFAULT 'pending',
        confirmed_by INTEGER,
        confirmed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_id) REFERENCES client_accounts(id),
        FOREIGN KEY (confirmed_by) REFERENCES users(id)
    )
''')
conn.commit()
print('✅ client_recharges 表创建成功')

# 3. 扣减记录表
print('\n=== 创建扣减记录表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS client_deductions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        sales_order_id INTEGER,
        sales_item_id INTEGER,
        amount REAL NOT NULL,
        quantity REAL DEFAULT 0,
        unit_price REAL DEFAULT 0,
        item_name TEXT,
        deduct_date DATE,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_id) REFERENCES client_accounts(id),
        FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id),
        FOREIGN KEY (sales_item_id) REFERENCES sales_order_items(id)
    )
''')
conn.commit()
print('✅ client_deductions 表创建成功')

# 4. 站内消息表
print('\n=== 创建站内消息表 ===')
cur.execute('''
    CREATE TABLE IF NOT EXISTS client_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        title TEXT,
        content TEXT,
        msg_type TEXT DEFAULT 'alert',
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_id) REFERENCES client_accounts(id)
    )
''')
conn.commit()
print('✅ client_messages 表创建成功')

# 5. 为users表添加role字段（如果没有）
print('\n=== 检查users表role字段 ===')
cur.execute("PRAGMA table_info(users)")
cols = [c[1] for c in cur.fetchall()]
if 'role' not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin'")
    conn.commit()
    print('✅ 添加 users.role 字段')
else:
    print('⏭️  users.role 已存在')

print('\n=== 验证 ===')
for table in ['client_accounts', 'client_recharges', 'client_deductions', 'client_messages']:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f'{table}: {cur.fetchone()[0]} 条记录')

conn.close()
