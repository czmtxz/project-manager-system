# -*- coding: utf-8 -*-
"""仅重导 Excel 出库扣减行（保留充值记录）。"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client_collab_ops import parse_collab_excel, import_outbound_rows, primary_client_for_company
from client_portal_utils import company_scope_client_ids


def recompute_client_balance(c, client_id):
    from datetime import datetime
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


def purge_deductions(c, customer_id):
    client = primary_client_for_company(c, customer_id=customer_id)
    scope_ids = company_scope_client_ids(c, client)
    ph = ','.join('?' * len(scope_ids))
    rows = c.execute(
        f"SELECT sales_item_id, sales_order_id FROM client_deductions WHERE client_id IN ({ph})",
        scope_ids,
    ).fetchall()
    item_ids = {r[0] for r in rows if r[0]}
    order_ids = {r[1] for r in rows if r[1]}
    n = c.execute(f"DELETE FROM client_deductions WHERE client_id IN ({ph})", scope_ids).rowcount
    for iid in item_ids:
        c.execute("DELETE FROM sales_order_items WHERE id=?", (iid,))
    for oid in order_ids:
        if c.execute("SELECT COUNT(*) FROM sales_order_items WHERE order_id=?", (oid,)).fetchone()[0] == 0:
            c.execute("DELETE FROM sales_orders WHERE id=?", (oid,))
    for cid in scope_ids:
        recompute_client_balance(c, cid)
    return client, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'project_manager.db'))
    ap.add_argument('--customer-id', type=int, required=True)
    ap.add_argument('--excel', required=True)
    ap.add_argument('--sheets', nargs='+', required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    client, deleted = purge_deductions(conn, args.customer_id)
    print(f'已删除扣减 {deleted} 条')

    total = 0
    for sn in args.sheets:
        parsed = parse_collab_excel(args.excel, mode='standard', sheet=sn)
        if parsed.get('error'):
            print(f'[{sn}] 跳过: {parsed["error"]}')
            continue
        rows = parsed.get('outbound_rows') or []
        cnt, amt, order_no, errs = import_outbound_rows(
            conn, args.customer_id, client['id'], rows, user_id=None,
        )
        total += cnt
        print(f'[{sn}] 扣减 {cnt} 条 / {amt:.2f} 元 ({order_no})')
        if errs:
            print('  警告:', '; '.join(errs[:5]))

    conn.commit()
    trucks = conn.execute(
        "SELECT COALESCE(SUM(truck_count),0) FROM client_deductions"
    ).fetchone()[0]
    bal = conn.execute(
        "SELECT balance, total_deduct FROM client_accounts WHERE id=?", (client['id'],)
    ).fetchone()
    print(f'车数合计: {trucks:g}  扣减合计: {bal[1]:.2f}  余额: {bal[0]:.2f}')
    conn.close()


if __name__ == '__main__':
    main()
