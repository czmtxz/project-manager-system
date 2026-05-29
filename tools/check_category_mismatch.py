import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

db = sqlite3.connect("project_manager.db")
pid = db.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()[0]

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = 1
    s["username"] = "admin"
    s["role"] = "admin"

html = client.get(f"/project/{pid}").data.decode("utf-8", errors="replace")
summary = re.findall(r'data-category="([^"]*)"', html)
m = re.search(r'data-filter="category"[^>]*>([\s\S]*?)</select>', html)
options = re.findall(r'<option value="([^"]*)"', m.group(1)) if m else []
missing = [c for c in summary if c and c not in options]
print("summary", len(summary), "options", len(options), "missing_in_select", len(missing))
if missing:
    print("examples:", missing[:8])
