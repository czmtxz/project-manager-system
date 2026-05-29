import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

c = app.test_client()
with c.session_transaction() as s:
    s["user_id"] = 1
    s["username"] = "admin"
    s["role"] = "admin"

r = c.get("/transactions")
html = r.data.decode("utf-8", errors="replace")
print("status", r.status_code)
print("has_title", "项目费用" in html)
print("has_table", "table-project-fees" in html)
print("has_summary_ids", "sum-fee-income" in html and "initProjectFeesTable" in html)
