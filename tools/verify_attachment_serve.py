# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, resolve_attachment_path, get_db


def main():
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT attachment FROM transaction_records "
            "WHERE source='image-ocr' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        print("no ocr record")
        return
    att = row["attachment"]
    rel = resolve_attachment_path(att)
    print("db attachment:", att)
    print("resolved:", rel)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
    r = client.get(f"/uploads/{att}")
    print("GET /uploads/ status:", r.status_code, "len:", len(r.data))
    assert r.status_code == 200, r.status_code
    print("OK")


if __name__ == "__main__":
    main()
