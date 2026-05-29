# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, get_db


def main():
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT id FROM transaction_records ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        print("no transactions, skip")
        return
    tid = row["id"]
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"

    r = client.get(f"/transaction/{tid}/edit")
    html = r.get_data(as_text=True)
    assert r.status_code == 200, r.status_code
    assert "编辑交易记录" in html, "title"
    assert 'name="amount"' in html and 'value="' in html, "amount field"
    # project should be pre-selected
    with app.app_context():
        db_row = get_db().execute(
            "SELECT project_id, amount, trans_date FROM transaction_records WHERE id=?",
            (tid,),
        ).fetchone()
    assert f'value="{db_row["trans_date"]}"' in html or (
        db_row["trans_date"] and db_row["trans_date"] in html
    ), "date not in form"
    assert str(db_row["amount"]) in html or f'{db_row["amount"]:.2f}' in html
    print("transaction_edit OK id=", tid)


if __name__ == "__main__":
    main()
