#!/usr/bin/env python3
"""
数据库迁移脚本：重构分类系统为三级结构
"""
import sqlite3
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project_manager.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("开始数据库迁移...")
    
    # 1. 备份原分类表
    print("1. 备份原分类表...")
    cursor.execute("ALTER TABLE categories RENAME TO categories_old")
    
    # 2. 创建新的三级分类表
    print("2. 创建新的三级分类表...")
    cursor.execute('''
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,           -- 科目编码，如 6001.01.01
            level INTEGER NOT NULL,     -- 级别：1=一级，2=二级，3=三级
            parent_id INTEGER,          -- 父级ID
            name TEXT NOT NULL,         -- 科目名称
            type TEXT NOT NULL,         -- income/expense
            direction TEXT,             -- 借贷方向：借/贷
            description TEXT,           -- 说明
            is_system INTEGER DEFAULT 1, -- 是否系统默认科目
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES categories(id)
        )
    ''')
    
    # 3. 创建项目-分类关联表
    print("3. 创建项目-分类关联表...")
    cursor.execute('''
        CREATE TABLE project_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
            UNIQUE(project_id, category_id)
        )
    ''')
    
    # 4. 迁移旧分类数据（作为一级分类）
    print("4. 迁移旧分类数据...")
    cursor.execute("SELECT * FROM categories_old ORDER BY sort_order, name")
    old_cats = cursor.fetchall()
    
    for cat in old_cats:
        cursor.execute('''
            INSERT INTO categories (name, level, type, description, sort_order, is_system)
            VALUES (?, 1, ?, ?, ?, 0)
        ''', (cat['name'], cat['type'], cat.get('description') or cat.get('keywords') or '', cat['sort_order'] or 0))
    
    # 5. 初始化会计准则三级科目
    print("5. 初始化会计准则三级科目...")
    init_accounting_categories(cursor)
    
    # 6. 删除旧表
    print("6. 清理旧表...")
    cursor.execute("DROP TABLE categories_old")
    
    conn.commit()
    conn.close()
    print("迁移完成！")

def init_accounting_categories(cursor):
    """初始化会计准则三级科目"""
    
    # 主营业务收入
    cursor.execute('''
        INSERT INTO categories (code, level, name, type, direction, description, sort_order)
        VALUES ('6001', 1, '主营业务收入', 'income', '贷', '企业主营业务产生的收入', 1)
    ''')
    income1_id = cursor.lastrowid
    
    # 二级：商品销售收入
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6001.01', 2, ?, '商品销售收入', 'income', '贷', '商品销售相关收入', 1)
    ''', (income1_id,))
    income1_1_id = cursor.lastrowid
    
    # 三级
    for i, name in enumerate(['自产产品销售收入', '外购商品销售收入', '原材料销售收入', '设备产品销售收入'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'income', '贷', '', ?)
        ''', (f'6001.01.{i:02d}', income1_1_id, name, i))
    
    # 二级：工程施工收入
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6001.02', 2, ?, '工程施工收入', 'income', '贷', '工程施工相关收入', 2)
    ''', (income1_id,))
    income1_2_id = cursor.lastrowid
    
    for i, name in enumerate(['建筑工程收入', '安装工程收入', '市政工程收入', '专项项目收入'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'income', '贷', '', ?)
        ''', (f'6001.02.{i:02d}', income1_2_id, name, i))
    
    # 二级：服务劳务收入
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6001.03', 2, ?, '服务劳务收入', 'income', '贷', '服务劳务相关收入', 3)
    ''', (income1_id,))
    income1_3_id = cursor.lastrowid
    
    for i, name in enumerate(['技术服务收入', '运维服务收入', '咨询服务收入', '加工劳务收入'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'income', '贷', '', ?)
        ''', (f'6001.03.{i:02d}', income1_3_id, name, i))
    
    # 二级：贸易经营收入
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6001.04', 2, ?, '贸易经营收入', 'income', '贷', '贸易经营相关收入', 4)
    ''', (income1_id,))
    income1_4_id = cursor.lastrowid
    
    for i, name in enumerate(['钢材贸易收入', '铝锭大宗商品收入', '建材贸易收入', '其他贸易收入'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'income', '贷', '', ?)
        ''', (f'6001.04.{i:02d}', income1_4_id, name, i))
    
    # 主营业务成本
    cursor.execute('''
        INSERT INTO categories (code, level, name, type, direction, description, sort_order)
        VALUES ('6401', 1, '主营业务成本', 'expense', '借', '企业主营业务产生的成本', 10)
    ''')
    expense1_id = cursor.lastrowid
    
    # 二级：商品销售成本
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6401.01', 2, ?, '商品销售成本', 'expense', '借', '商品销售相关成本', 1)
    ''', (expense1_id,))
    expense1_1_id = cursor.lastrowid
    
    for i, name in enumerate(['自产产品销售成本', '外购商品进货成本', '原材料销售成本', '设备销售成本'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
        ''', (f'6401.01.{i:02d}', expense1_1_id, name, i))
    
    # 二级：工程施工成本
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6401.02', 2, ?, '工程施工成本', 'expense', '借', '工程施工相关成本', 2)
    ''', (expense1_id,))
    expense1_2_id = cursor.lastrowid
    
    for i, name in enumerate(['工程材料费', '工程人工费', '分包工程款', '机械使用费', '工程杂费'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
        ''', (f'6401.02.{i:02d}', expense1_2_id, name, i))
    
    # 二级：服务劳务成本
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6401.03', 2, ?, '服务劳务成本', 'expense', '借', '服务劳务相关成本', 3)
    ''', (expense1_id,))
    expense1_3_id = cursor.lastrowid
    
    for i, name in enumerate(['服务人员薪酬成本', '服务耗材成本', '劳务外包成本'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
        ''', (f'6401.03.{i:02d}', expense1_3_id, name, i))
    
    # 二级：贸易业务成本
    cursor.execute('''
        INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
        VALUES ('6401.04', 2, ?, '贸易业务成本', 'expense', '借', '贸易业务相关成本', 4)
    ''', (expense1_id,))
    expense1_4_id = cursor.lastrowid
    
    for i, name in enumerate(['商品采购成本', '贸易运输费', '贸易装卸仓储费', '贸易杂费成本'], 1):
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
        ''', (f'6401.04.{i:02d}', expense1_4_id, name, i))
    
    # 管理费用
    cursor.execute('''
        INSERT INTO categories (code, level, name, type, direction, description, sort_order)
        VALUES ('6602', 1, '管理费用', 'expense', '借', '企业管理部门发生的费用', 20)
    ''')
    mgmt_id = cursor.lastrowid
    
    # 管理费用二级科目
    mgmt_items = [
        ('6602.01', '薪酬福利费', ['管理人员工资', '社保公积金', '职工福利费', '团建会务福利', '劳务外包服务费']),
        ('6602.02', '办公物业费用', ['办公场地租赁费', '物业保洁保安费', '水电取暖费', '通讯网络费', '办公耗材费', '办公设备维修费']),
        ('6602.03', '差旅招待费用', ['管理人员差旅费', '业务招待费']),
        ('6602.04', '中介咨询费用', ['审计验资评估费', '法律顾问费', '管理咨询费', '工商资质服务费']),
        ('6602.05', '折旧摊销费用', ['房屋建筑物折旧', '办公设备折旧', '运输车辆折旧', '无形资产摊销', '长期待摊摊销']),
        ('6602.06', '税费及其他', ['财产行为税费', '其他管理杂费']),
    ]
    
    for code, name, children in mgmt_items:
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 2, ?, ?, 'expense', '借', '', ?)
        ''', (code, mgmt_id, name, int(code.split('.')[1])))
        parent_id = cursor.lastrowid
        
        for i, child_name in enumerate(children, 1):
            cursor.execute('''
                INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
                VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
            ''', (f'{code}.{i:02d}', parent_id, child_name, i))
    
    # 销售费用
    cursor.execute('''
        INSERT INTO categories (code, level, name, type, direction, description, sort_order)
        VALUES ('6601', 1, '销售费用', 'expense', '借', '企业销售部门发生的费用', 30)
    ''')
    sales_id = cursor.lastrowid
    
    sales_items = [
        ('6601.01', '销售薪酬福利', ['销售人员工资提成', '销售社保公积金', '销售部门福利费']),
        ('6601.02', '推广宣传费用', ['广告投放费', '展会展位费', '宣传物料制作费', '平台运营推广费']),
        ('6601.03', '渠道业务费用', ['渠道返利补贴', '居间服务费', '渠道维护费']),
        ('6601.04', '物流门店费用', ['运输装卸费', '仓储保管费', '销售门店租金装修费', '产品包装费']),
        ('6601.05', '销售其他费用', ['销售差旅费', '销售业务招待费', '售后维修费', '其他销售杂费']),
    ]
    
    for code, name, children in sales_items:
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 2, ?, ?, 'expense', '借', '', ?)
        ''', (code, sales_id, name, int(code.split('.')[1])))
        parent_id = cursor.lastrowid
        
        for i, child_name in enumerate(children, 1):
            cursor.execute('''
                INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
                VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
            ''', (f'{code}.{i:02d}', parent_id, child_name, i))
    
    # 财务费用
    cursor.execute('''
        INSERT INTO categories (code, level, name, type, direction, description, sort_order)
        VALUES ('6603', 1, '财务费用', 'expense', '借', '企业筹资发生的费用', 40)
    ''')
    finance_id = cursor.lastrowid
    
    finance_items = [
        ('6603.01', '利息收支', ['贷款利息支出', '票据贴现利息']),
        ('6603.02', '银行手续费', ['转账汇款手续费', '网银账户服务费', '票据手续费']),
        ('6603.03', '汇兑损益', ['外币汇兑损失', '外币汇兑收益']),
        ('6603.04', '其他财务费用', ['融资服务费', '资金占用费', '其他财务杂费']),
    ]
    
    for code, name, children in finance_items:
        cursor.execute('''
            INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
            VALUES (?, 2, ?, ?, 'expense', '借', '', ?)
        ''', (code, finance_id, name, int(code.split('.')[1])))
        parent_id = cursor.lastrowid
        
        for i, child_name in enumerate(children, 1):
            cursor.execute('''
                INSERT INTO categories (code, level, parent_id, name, type, direction, description, sort_order)
                VALUES (?, 3, ?, ?, 'expense', '借', '', ?)
            ''', (f'{code}.{i:02d}', parent_id, child_name, i))

if __name__ == '__main__':
    migrate()
