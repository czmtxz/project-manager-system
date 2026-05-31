# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client_collab_ops import summarize_collab_excel_sheets

for path in sys.argv[1:]:
    print('===', path, '===')
    s = summarize_collab_excel_sheets(path, mode='standard')
    if s.get('error'):
        print('ERROR:', s['error'])
        continue
    for x in s.get('sheets', []):
        print(x.get('name'), 'recharge', x.get('recharge_count'), 'outbound', x.get('outbound_count'), 'dup', x.get('is_duplicate'))
