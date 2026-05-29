"""E2E: verify project detail column filters via Playwright. Writes debug-984449.log."""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG_PATH = Path(__file__).resolve().parent.parent / "debug-984449.log"
SESSION = "984449"


def log(hypothesis_id, location, message, data, run_id="e2e-verify"):
    line = json.dumps(
        {
            "sessionId": SESSION,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "runId": run_id,
        },
        ensure_ascii=False,
    )
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    import threading
    from werkzeug.serving import make_server

    from app import app

    db = sqlite3.connect("project_manager.db")
    pid = db.execute("SELECT id FROM projects ORDER BY id DESC LIMIT 1").fetchone()[0]
    tx = db.execute(
        "SELECT COUNT(*) FROM transaction_records WHERE project_id=?", (pid,)
    ).fetchone()[0]
    if tx < 1:
        log("H0", "e2e", "skip no transactions", {"pid": pid})
        print("SKIP: no transactions")
        return 0

    server = make_server("127.0.0.1", 5099, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:5099"

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{base}/login")
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "admin123")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

            page.goto(f"{base}/project/{pid}")
            page.wait_for_selector("#table-transaction", timeout=10000)

            total_before = page.locator("#table-transaction tbody tr").count()
            visible_before = page.evaluate(
                """() => Array.from(document.querySelectorAll('#table-transaction tbody tr'))
                .filter(r => r.style.display !== 'none').length"""
            )
            log(
                "H1",
                "e2e:before",
                "rows before filter",
                {"total": total_before, "visible": visible_before},
            )

            page.select_option(
                '#table-transaction thead .col-filter[data-filter="type"]', "income"
            )
            page.wait_for_timeout(200)
            visible_after = page.evaluate(
                """() => Array.from(document.querySelectorAll('#table-transaction tbody tr'))
                .filter(r => r.style.display !== 'none').length"""
            )
            income_sum = page.locator("#sum-trans-income").inner_text()
            log(
                "H1",
                "e2e:after_type_income",
                "rows after income filter",
                {
                    "visible": visible_after,
                    "income_sum": income_sum,
                    "filtered": visible_after < visible_before,
                },
            )

            page.click("#table-transaction .btn-clear-filters")
            page.wait_for_timeout(200)
            visible_cleared = page.evaluate(
                """() => Array.from(document.querySelectorAll('#table-transaction tbody tr'))
                .filter(r => r.style.display !== 'none').length"""
            )
            log(
                "H3",
                "e2e:after_clear",
                "rows after clear",
                {"visible": visible_cleared, "restored": visible_cleared == visible_before},
            )

            boot_ok = page.evaluate(
                "() => typeof applyColumnFilters === 'function' && typeof bootDetailTableFilters === 'function'"
            )
            log("H3", "e2e:boot", "js functions present", {"ok": boot_ok})

            browser.close()

            ok = boot_ok and visible_after < visible_before and visible_cleared == visible_before
            print("PASS" if ok else "FAIL", "before", visible_before, "after", visible_after, "cleared", visible_cleared)
            return 0 if ok else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    sys.exit(main())
