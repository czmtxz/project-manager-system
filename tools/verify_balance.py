# -*- coding: utf-8 -*-
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client_portal_utils import compute_balance_totals, get_client_by_id, LOW_BALANCE_THRESHOLD

db_path = sys.argv[1] if len(sys.argv) > 1 else 'data.db'
client_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1

db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row
client = get_client_by_id(db, client_id)
if not client:
    print('client not found')
    sys.exit(1)
balance, recharge, deduct = compute_balance_totals(db, client)
print(f'balance={balance:.2f} recharge={recharge:.2f} deduct={deduct:.2f}')
print(f'formula_check={recharge - deduct:.2f}')
print(f'threshold={LOW_BALANCE_THRESHOLD} low={balance < LOW_BALANCE_THRESHOLD}')
