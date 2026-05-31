# -*- coding: utf-8 -*-
"""统计 Excel 中销售单价与销售金额均为 0 的行数。"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client_collab_ops import _cell_date, _cell_str, _excel_col_map, _load_sheet_df, _parse_float

p = Path(sys.argv[1] if len(sys.argv) > 1 else r'\\DESKTOP-VMPGRAC\download\PPT\虎子   泽永(8).xlsx')
sheets = sys.argv[2:] if len(sys.argv) > 2 else ['虎子 (3)', '虎子 (4)']

for sn in sheets:
    df = _load_sheet_df(pd, str(p), sn)
    find = _excel_col_map(df)
    c_sales_amount = find('销售金额')
    c_unit_price = find('单价')
    c_tons = find('销售吨数')
    c_spec = find('规格')
    skipped = 0
    would_import = 0
    for idx, r in enumerate(df.to_dict('records'), 2):
        sales_amount = _parse_float(r.get(c_sales_amount)) if c_sales_amount else 0
        unit_price = _parse_float(r.get(c_unit_price)) if c_unit_price else 0
        tons = _parse_float(r.get(c_tons)) if c_tons else 0
        if sales_amount <= 0 and tons > 0 and unit_price > 0:
            sales_amount = round(tons * unit_price, 2)
        if unit_price <= 0 and sales_amount <= 0:
            skipped += 1
        elif sales_amount > 0:
            would_import += 1
    print(sn, 'skip_both_zero', skipped, 'import', would_import)
