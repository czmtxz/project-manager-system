# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app
from client_portal_utils import ensure_schema_extensions

with app.app_context():
    from app import get_db
    ensure_schema_extensions(get_db())
    print('schema ok')
