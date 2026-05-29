"""Simulate applyColumnFilters on rendered HTML; append debug-984449.log."""
import json
import os
import re
import sqlite3
import sys
import time
from html import unescape
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

LOG = Path(__file__).resolve().parent.parent / "debug-984449.log"
SESSION = "984449"


def log(hid, loc, msg, data, run_id="e2e-simulate"):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "sessionId": SESSION,
                    "hypothesisId": hid,
                    "location": loc,
                    "message": msg,
                    "data": data,
                    "timestamp": int(time.time() * 1000),
                    "runId": run_id,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def parse_rows(html, table_id):
    chunk = html.split(f'id="{table_id}"', 1)[1].split("</table>", 1)[0]
    rows = []
    for m in re.finditer(r"<tr([^>]*)>", chunk):
        attrs = m.group(1)
        data = {}
        for k, v in re.findall(r'data-filter-(\w+)="([^"]*)"', attrs):
            data[k] = unescape(v)
        if data:
            rows.append(data)
    return rows


def apply(rows, criteria, exact_keys):
    visible = []
    for row in rows:
        ok = True
        for key, val in criteria.items():
            raw = (row.get(key) or "").lower()
            v = val.lower()
            if key in exact_keys:
                if raw != v:
                    ok = False
                    break
            elif v not in raw:
                ok = False
                break
        if ok:
            visible.append(row)
    return visible


def main():
    if LOG.exists():
        LOG.unlink()
    db = sqlite3.connect("project_manager.db")
    pid = db.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()[0]
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "admin"
        s["role"] = "admin"
    html = client.get(f"/project/{pid}").data.decode("utf-8", errors="replace")
    rows = parse_rows(html, "table-transaction")
    log("H3", "simulate:boot", "parsed rows", {"count": len(rows), "pid": pid})

    all_visible = apply(rows, {}, set())
    income_visible = apply(rows, {"type": "income"}, {"type", "category"})
    log(
        "H1",
        "simulate:income",
        "filter type=income",
        {
            "total": len(rows),
            "visible_all": len(all_visible),
            "visible_income": len(income_visible),
            "filtered": len(income_visible) < len(all_visible),
        },
    )

    if rows:
        sample = rows[0]
        person_key = "person"
        if sample.get("person"):
            pval = sample["person"][:2]
            p_visible = apply(rows, {"person": pval}, {"type", "category"})
            log(
                "H1",
                "simulate:person",
                "text filter person",
                {"needle": pval, "visible": len(p_visible), "works": 0 < len(p_visible) <= len(rows)},
            )

    ok = len(rows) > 0 and len(income_visible) < len(all_visible)
    log("H1", "simulate:result", "verification", {"pass": ok})
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
