#!/usr/bin/env python3
"""Add api_transport_delete route if missing."""
from pathlib import Path

APP = Path('/opt/project_manager/project_manager/app.py')
text = APP.read_text(encoding='utf-8')
if "def api_transport_delete" in text:
    print('delete route already exists')
    raise SystemExit(0)

marker = "@app.route('/api/transport/save', methods=['POST'])"
block = """

@app.route('/api/transport/<int:id>/delete', methods=['POST'])
@login_required
def api_transport_delete(id):
    \"\"\"删除运输记录\"\"\"
    db = get_db()
    record = db.execute("SELECT id FROM transport_records WHERE id=?", (id,)).fetchone()
    if not record:
        return jsonify({'success': False, 'message': '记录不存在'}), 404
    db.execute("DELETE FROM transport_purchase_items WHERE transport_id=?", (id,))
    db.execute("DELETE FROM sales_item_transport WHERE transport_id=?", (id,))
    db.execute("DELETE FROM transport_records WHERE id=?", (id,))
    db.commit()
    add_log(session.get('user_id'), session.get('username', ''), '删除运输记录', f'记录ID: {id}')
    return jsonify({'success': True})

"""
if marker not in text:
    raise SystemExit('save route marker not found')

APP.write_text(text.replace(marker, block + marker, 1), encoding='utf-8')
print('added transport delete route')
