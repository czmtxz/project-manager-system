# -*- coding: utf-8 -*-
"""将 OCR 导入记录的 attachment 统一为 ocr/ 前缀（可选一次性修复）。"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "project_manager.db"


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, attachment, source FROM transaction_records "
        "WHERE attachment IS NOT NULL AND attachment != ''"
    ).fetchall()
    updated = 0
    for rid, att, source in rows:
        if not att or '/' in att.replace('\\', '/'):
            continue
        if source == 'image-ocr' or att.startswith('ocr_'):
            conn.execute(
                "UPDATE transaction_records SET attachment=? WHERE id=?",
                (f"ocr/{att}", rid),
            )
            updated += 1
    conn.commit()
    print(f"updated {updated} rows")


if __name__ == "__main__":
    main()
