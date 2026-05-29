"""验证项目分类白名单；写入 debug-984449.log"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from project_category_utils import (
    get_grouped_categories_json,
    get_project_enabled_category_ids,
    project_uses_category_whitelist,
)

LOG = Path(__file__).resolve().parent.parent / "debug-984449.log"
SESSION = "984449"


def log(hid, loc, msg, data):
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
                    "runId": "category-whitelist",
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def main():
    if LOG.exists():
        LOG.unlink()
    db = sqlite3.connect("project_manager.db")
    db.row_factory = sqlite3.Row
    proj = db.execute(
        "SELECT id, name FROM projects WHERE name LIKE ? LIMIT 1", ("%砂石%",)
    ).fetchone()
    if not proj:
        log("H0", "verify", "no project", {})
        print("FAIL no project")
        return 1
    pid = proj["id"]

    uses = project_uses_category_whitelist(db, pid)
    enabled = get_project_enabled_category_ids(db, pid)
    grouped = get_grouped_categories_json(db, pid)
    log(
        "H1",
        "verify:whitelist",
        "project whitelist state",
        {
            "project_id": pid,
            "uses_whitelist": uses,
            "enabled_count": len(enabled),
            "enabled_ids": enabled,
            "expense_names": [c["name"] for c in grouped["expense"]],
            "income_count": len(grouped["income"]),
        },
    )

    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "admin"
        s["role"] = "admin"

    r = client.get(f"/api/project/{pid}/categories/grouped")
    api_data = r.get_json()
    log(
        "H2",
        "verify:api",
        "grouped API",
        {
            "status": r.status_code,
            "expense_count": len(api_data.get("expense", [])),
            "expense_names": [c.get("name") for c in api_data.get("expense", [])],
        },
    )

    html = client.get(f"/project/{pid}").data.decode("utf-8", errors="replace")
    log(
        "H3",
        "verify:page",
        "project detail page",
        {
            "has_tab": "tab-categories" in html,
            "expense_option_count": html.count('data-filter="category"'),
        },
    )

    ok = (
        uses
        and len(enabled) == 2
        and r.status_code == 200
        and len(api_data.get("expense", [])) == 2
    )
    log("H1", "verify:result", "pass" if ok else "fail", {"ok": ok})
    print("PASS" if ok else "FAIL", "enabled", enabled, "api expense", len(api_data.get("expense", [])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
