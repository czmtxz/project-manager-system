# -*- coding: utf-8 -*-
import sys, json
sys.path.insert(0, '.')
from openpyxl import load_workbook
from client_collab_ops import parse_collab_excel

P = r'\\DESKTOP-VMPGRAC\download\PPT\虎子   泽永(8).xlsx'

wb = load_workbook(P, read_only=True)
print('=== sheets (name | state) ===')
for ws in wb.worksheets:
    print(repr(ws.title), '|', ws.sheet_state)
wb.close()

print('=== parse per sheet ===')
import pandas as pd
for sn in pd.ExcelFile(P).sheet_names:
    r = parse_collab_excel(P, mode='standard', sheet=sn)
    if r.get('error'):
        print(repr(sn), '-> error', r['error'][:30])
        continue
    rch = r.get('recharge_rows', [])
    obd = r.get('outbound_rows', [])
    print(repr(sn), '| recharge', len(rch), 'sum', round(sum(float(x['amount']) for x in rch),2),
          '| outbound', len(obd), 'sum', round(sum(float(x['amount']) for x in obd),2))
    # show first recharge & outbound row
    if rch: print('   rch[0]:', {k: rch[0].get(k) for k in ('recharge_date','amount','remark')})
    if obd: print('   obd[0]:', {k: obd[0].get(k) for k in ('deduct_date','item_name','quantity','unit_price','amount','remark')})
