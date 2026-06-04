#!/usr/bin/env python3
"""Fix sales order detail transport display: query by sales_order_id, pass transports."""
from pathlib import Path

APP = Path('/opt/project_manager/project_manager/app.py')
text = APP.read_text(encoding='utf-8')
APP.with_suffix('.py.bak_sales_transport').write_text(text, encoding='utf-8')

old = """    # 关联的运输记录
    transport_ids = db.execute(\"\"\"SELECT DISTINCT sit.transport_id
                                  FROM sales_item_transport sit
                                  JOIN sales_order_items soi ON sit.sales_item_id = soi.id
                                  WHERE soi.sales_order_id = ?\"\"\", (id,)).fetchall()
    transport_list = []
    if transport_ids:
        tid_str = ','.join([str(t['transport_id']) for t in transport_ids])
        transport_list = db.execute(f\"\"\"SELECT tr.* FROM transport_records tr
                                         WHERE tr.id IN ({tid_str}) ORDER BY tr.transport_date\"\"\").fetchall()

    # 计算汇总数据
    total_item_qty = sum(float(i['quantity'] or 0) for i in items)
    total_item_amount = sum(float(i['amount'] or 0) for i in items)
    total_transport_qty = sum(float(t['quantity'] or 0) for t in transport_list)
    total_freight = sum(float(t['freight_amount'] or 0) for t in transport_list)
    total_linked_qty = sum(float(i['linked_quantity'] or 0) for i in items)

    return render_template('sales_order_detail.html', order=order, items=items,
                           transport_list=transport_list,"""

new = """    # 运输记录：优先按 sales_order_id 直接关联，并合并明细关联表中的记录
    tr_cols = {r[1] for r in db.execute('PRAGMA table_info(transport_records)').fetchall()}
    transports = []
    seen_ids = set()
    if 'sales_order_id' in tr_cols:
        for row in db.execute(
            \"\"\"SELECT tr.* FROM transport_records tr
               WHERE tr.sales_order_id = ?
               ORDER BY tr.transport_date, tr.id\"\"\",
            (id,),
        ).fetchall():
            transports.append(row)
            seen_ids.add(row['id'])
    linked_ids = db.execute(
        \"\"\"SELECT DISTINCT sit.transport_id
           FROM sales_item_transport sit
           JOIN sales_order_items soi ON sit.sales_item_id = soi.id
           WHERE soi.sales_order_id = ?\"\"\",
        (id,),
    ).fetchall()
    extra_ids = [t['transport_id'] for t in linked_ids if t['transport_id'] not in seen_ids]
    if extra_ids:
        tid_str = ','.join(str(i) for i in extra_ids)
        transports.extend(
            db.execute(
                f\"\"\"SELECT tr.* FROM transport_records tr
                    WHERE tr.id IN ({tid_str})
                    ORDER BY tr.transport_date, tr.id\"\"\"
            ).fetchall()
        )
        transports.sort(key=lambda t: (t['transport_date'] or '', t['id'] or 0))

    # 计算汇总数据
    total_item_qty = sum(float(i['quantity'] or 0) for i in items)
    total_item_amount = sum(float(i['amount'] or 0) for i in items)
    total_transport_qty = sum(float(t['quantity'] or 0) for t in transports)
    total_freight = sum(float(t['freight_amount'] or 0) for t in transports)
    total_linked_qty = sum(float(i['linked_quantity'] or 0) for i in items)

    return render_template('sales_order_detail.html', order=order, items=items,
                           transports=transports,"""

if old not in text:
    raise SystemExit('patch target not found in app.py')

APP.write_text(text.replace(old, new, 1), encoding='utf-8')
print('patched sales transport display')
