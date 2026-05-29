# -*- coding: utf-8 -*-
"""报表中心用户收藏与主题偏好表"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'project_manager.db'


def run():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    from report_hub_prefs import ensure_report_hub_prefs_schema
    ensure_report_hub_prefs_schema(conn)
    conn.close()
    print('report_hub_user_prefs migration OK')


if __name__ == '__main__':
    run()
