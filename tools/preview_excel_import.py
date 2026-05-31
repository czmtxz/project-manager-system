# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client_collab_ops import parse_collab_excel, summarize_collab_excel_sheets

p = Path(r'\\DESKTOP-VMPGRAC\download\PPT\虎子   泽永(8).xlsx')
print('exists', p.exists())
for sn in pd.ExcelFile(p).sheet_names:
    r = parse_collab_excel(str(p), mode='standard', sheet=sn)
    if r.get('error'):
        print(repr(sn), 'ERROR', r['error'][:60])
    else:
        print(repr(sn), 'recharge', len(r.get('recharge_rows') or []),
              'outbound', len(r.get('outbound_rows') or []))

s = summarize_collab_excel_sheets(str(p))
for x in s.get('sheets', []):
    print('SUM', x['sheet'], x['recharge_count'], x['outbound_count'], 'dup', x.get('is_duplicate'))
