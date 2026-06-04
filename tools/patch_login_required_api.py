#!/usr/bin/env python3
"""Patch login_required to return JSON 401 for /api/ routes."""
from pathlib import Path

APP = Path('/opt/project_manager/project_manager/app.py')
text = APP.read_text(encoding='utf-8')
old = """def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function"""

new = """def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': '请先登录'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function"""

if old not in text:
    raise SystemExit('login_required patch target not found')
APP.write_text(text.replace(old, new, 1), encoding='utf-8')
print('patched login_required')
