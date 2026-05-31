# -*- coding: utf-8 -*-
"""仅重导 Excel 充值行，状态为待审核（不影响扣减记录）。"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client_collab_ops import parse_collab_excel, import_recharge_rows, primary_client_for_company
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


def purge_recharges(c, customer_id):
    client = primary_client_for_company(c, customer_id=customer_id)
    scope_ids = company_scope_client_ids(c, client)
    ph = ','.join('?' * len(scope_ids))
    n = c.execute(f"DELETE FROM client_recharges WHERE client_id IN ({ph})", scope_ids).rowcount
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
    client, deleted = purge_recharges(conn, args.customer_id)
    print(f'已删除充值 {deleted} 条')

    total = 0
    for sn in args.sheets:
        parsed = parse_collab_excel(args.excel, mode='standard', sheet=sn)
        if parsed.get('error'):
            print(f'[{sn}] 跳过: {parsed["error"]}')
            continue
        rows = parsed.get('recharge_rows') or []
        ok, errs = import_recharge_rows(conn, client['id'], rows, user_id=None, auto_confirm=False)
        total += ok
        print(f'[{sn}] 待审核充值 {ok} 条')
        if errs:
            print('  警告:', '; '.join(errs[:5]))

    conn.commit()
    pending = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM client_recharges WHERE status='pending'"
    ).fetchone()
    bal = conn.execute(
        "SELECT balance, total_recharge FROM client_accounts WHERE id=?", (client['id'],)
    ).fetchone()
    print(f'待审核: {pending[0]} 条 / {pending[1]:.2f} 元')
    print(f'账户余额: {bal[0]:.2f}  已确认充值: {bal[1]:.2f}')
    conn.close()


if __name__ == '__main__':
    main()
