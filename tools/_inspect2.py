# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, '.')
from openpyxl import load_workbook
from client_collab_ops import summarize_collab_excel_sheets

P = sys.argv[1]
wb = load_workbook(P, read_only=True)
states = {ws.title: ws.sheet_state for ws in wb.worksheets}
wb.close()

summ = summarize_collab_excel_sheets(P)
out = {'order': list(states.keys()), 'states': states, 'sheets': summ.get('sheets', [])}
with open('tools/_inspect2.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print('written tools/_inspect2.json')
