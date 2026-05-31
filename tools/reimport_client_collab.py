# -*- coding: utf-8 -*-
"""删除客户协同充值/扣减数据并按 Excel 页签重新导入。"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client_collab_ops import (  # noqa: E402
    import_standard_excel_bundle,
    parse_collab_excel,
    primary_client_for_company,
    summarize_collab_excel_sheets,
)
from client_portal_utils import company_scope_client_ids  # noqa: E402


def recompute_client_balance(c, client_id):
    rech = c.execute(
        "SELECT COALESCE(SUM(amount),0) FROM client_recharges "
        "WHERE client_id=? AND status='confirmed'",
        (client_id,),
    ).fetchone()[0]
    ded = c.execute(
        "SELECT COALESCE(SUM(amount),0) FROM client_deductions WHERE client_id=?",
        (client_id,),
    ).fetchone()[0]
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute(
        "UPDATE client_accounts SET total_recharge=?, total_deduct=?, balance=?, updated_at=? WHERE id=?",
        (rech, ded, float(rech) - float(ded), now, client_id),
    )


def purge_company_collab_data(c, customer_id, clear_recharges=True, clear_deductions=True):
    client = primary_client_for_company(c, customer_id=customer_id)
    if not client:
        raise SystemExit(f'customer_id={customer_id} 无有效客户账号')
    scope_ids = company_scope_client_ids(c, client)
    if not scope_ids:
        raise SystemExit('无 client_id 范围')
    ph = ','.join('?' * len(scope_ids))
    deleted = {'recharges': 0, 'deductions': 0, 'orders': 0}

    if clear_deductions:
        rows = c.execute(
            f"SELECT sales_item_id, sales_order_id FROM client_deductions WHERE client_id IN ({ph})",
            scope_ids,
        ).fetchall()
        item_ids = {r[0] for r in rows if r[0]}
        order_ids = {r[1] for r in rows if r[1]}
        cur = c.execute(f"DELETE FROM client_deductions WHERE client_id IN ({ph})", scope_ids)
        deleted['deductions'] = cur.rowcount
        for iid in item_ids:
            c.execute("DELETE FROM sales_order_items WHERE id=?", (iid,))
        for oid in order_ids:
            left = c.execute(
                "SELECT COUNT(*) FROM sales_order_items WHERE order_id=?", (oid,)
            ).fetchone()[0]
            if left == 0:
                c.execute("DELETE FROM sales_orders WHERE id=?", (oid,))
                deleted['orders'] += 1

    if clear_recharges:
        cur = c.execute(f"DELETE FROM client_recharges WHERE client_id IN ({ph})", scope_ids)
        deleted['recharges'] = cur.rowcount

    for cid in scope_ids:
        recompute_client_balance(c, cid)
    return client, deleted


def main():
    ap = argparse.ArgumentParser(description='清空并重新导入客户协同 Excel')
    ap.add_argument('--db', default=str(ROOT / 'project_manager.db'))
    ap.add_argument('--customer-id', type=int, required=True)
    ap.add_argument('--excel', required=True, help='Excel 文件路径')
    ap.add_argument('--sheets', nargs='+', help='页签名称；省略则导入全部非重复页签')
    ap.add_argument('--skip-recharges', action='store_true', help='仅重导扣减，保留充值')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.is_file():
        raise SystemExit(f'文件不存在: {excel_path}')

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    client, deleted = purge_company_collab_data(
        conn, args.customer_id,
        clear_recharges=not args.skip_recharges,
        clear_deductions=True,
    )
    print(f"已清理 customer_id={args.customer_id}: 充值 {deleted['recharges']} 条, "
          f"扣减 {deleted['deductions']} 条, 出库单 {deleted['orders']} 张")

    if args.sheets:
        sheet_names = args.sheets
    else:
        summary = summarize_collab_excel_sheets(str(excel_path), mode='standard')
        if summary.get('error'):
            raise SystemExit(summary['error'])
        sheet_names = [
            s['sheet'] for s in summary.get('sheets', [])
            if not s.get('is_duplicate')
        ]
    if not sheet_names:
        raise SystemExit('没有可导入的页签')

    if args.dry_run:
        conn.rollback()
        print('dry-run: 已回滚，未写入导入数据')
        for sn in sheet_names:
            parsed = parse_collab_excel(str(excel_path), mode='standard', sheet=sn)
            ob = len(parsed.get('outbound_rows') or [])
            rc = len(parsed.get('recharge_rows') or [])
            print(f"  [{sn}] 充值 {rc} 条, 扣减 {ob} 条")
        return

    parts = []
    errs = []
    for sn in sheet_names:
        parsed = parse_collab_excel(str(excel_path), mode='standard', sheet=sn)
        if parsed.get('error'):
            errs.append(f'{sn}: {parsed["error"]}')
            continue
        ok, msg, er = import_standard_excel_bundle(
            conn, args.customer_id, client['id'], parsed, user_id=None,
        )
        if ok:
            parts.append(f'【{sn}】{msg}')
        else:
            errs.append(f'{sn}: {msg}')
        errs.extend(er)

    conn.commit()
    print('导入完成: ' + '；'.join(parts))
    if errs:
        print('警告: ' + '; '.join(errs[:10]))

    bal = conn.execute(
        "SELECT balance, total_recharge, total_deduct FROM client_accounts WHERE id=?",
        (client['id'],),
    ).fetchone()
    print(f"余额: {bal[0]:.2f}  充值: {bal[1]:.2f}  扣减: {bal[2]:.2f}")
    conn.close()


if __name__ == '__main__':
    main()
