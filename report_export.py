# -*- coding: utf-8 -*-
"""报表 Excel 导出"""
import io
from datetime import datetime


def export_to_xlsx(title, rows, columns=None):
    """将行数据导出为 xlsx 字节流。"""
    import pandas as pd

    if not rows:
        df = pd.DataFrame(columns=columns or [])
    elif columns:
        df = pd.DataFrame(rows)
        existing = [c for c in columns if c in df.columns]
        extra = [c for c in df.columns if c not in columns]
        df = df[existing + extra]
    else:
        df = pd.DataFrame(rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        sheet = (title or '报表')[:31]
        df.to_excel(writer, index=False, sheet_name=sheet)
    buf.seek(0)
    return buf


def export_filename(title, date_from, date_to):
    safe = (title or 'report').replace('/', '-').replace('\\', '-')
    ts = datetime.now().strftime('%Y%m%d')
    return f'{safe}_{date_from}_{date_to}_{ts}.xlsx'
