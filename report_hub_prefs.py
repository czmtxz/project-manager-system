# -*- coding: utf-8 -*-
"""报表中心：用户收藏与界面偏好（按账号）"""
import json
from datetime import datetime


def ensure_report_hub_prefs_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_report_hub_prefs (
            user_id INTEGER PRIMARY KEY,
            favorite_slugs TEXT NOT NULL DEFAULT '[]',
            dark_mode INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_report_favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, slug),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_fav_user
        ON user_report_favorites(user_id)
    """)
    db.commit()


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_hub_prefs(db, user_id):
    ensure_report_hub_prefs_schema(db)
    row = db.execute(
        'SELECT favorite_slugs, dark_mode FROM user_report_hub_prefs WHERE user_id=?',
        (user_id,),
    ).fetchone()
    if row:
        try:
            favs = json.loads(row['favorite_slugs'] or '[]')
        except (TypeError, json.JSONDecodeError):
            favs = []
        return {
            'favorites': favs if isinstance(favs, list) else [],
            'dark_mode': bool(row['dark_mode']),
        }
    rows = db.execute(
        'SELECT slug FROM user_report_favorites WHERE user_id=? ORDER BY sort_order, id',
        (user_id,),
    ).fetchall()
    favs = [r['slug'] for r in rows]
    if favs:
        _sync_favorites_json(db, user_id, favs, False)
    return {'favorites': favs, 'dark_mode': False}


def _sync_favorites_json(db, user_id, slugs, dark_mode=None):
    now = _now()
    existing = db.execute(
        'SELECT dark_mode FROM user_report_hub_prefs WHERE user_id=?', (user_id,)
    ).fetchone()
    dm = int(dark_mode) if dark_mode is not None else (
        int(existing['dark_mode']) if existing else 0
    )
    payload = json.dumps(slugs, ensure_ascii=False)
    if existing:
        db.execute(
            """UPDATE user_report_hub_prefs
               SET favorite_slugs=?, dark_mode=?, updated_at=? WHERE user_id=?""",
            (payload, dm, now, user_id),
        )
    else:
        db.execute(
            """INSERT INTO user_report_hub_prefs (user_id, favorite_slugs, dark_mode, updated_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, payload, dm, now),
        )
    db.commit()


def set_dark_mode(db, user_id, enabled):
    ensure_report_hub_prefs_schema(db)
    prefs = get_hub_prefs(db, user_id)
    _sync_favorites_json(db, user_id, prefs['favorites'], bool(enabled))
    return bool(enabled)


def get_favorite_slugs(db, user_id):
    return get_hub_prefs(db, user_id)['favorites']


def is_favorited(db, user_id, slug):
    return slug in get_favorite_slugs(db, user_id)


def toggle_favorite(db, user_id, slug):
    ensure_report_hub_prefs_schema(db)
    favs = get_favorite_slugs(db, user_id)
    if slug in favs:
        favs = [s for s in favs if s != slug]
        favorited = False
    else:
        favs = favs + [slug]
        favorited = True
    now = _now()
    db.execute('DELETE FROM user_report_favorites WHERE user_id=?', (user_id,))
    for i, s in enumerate(favs):
        db.execute(
            """INSERT INTO user_report_favorites (user_id, slug, sort_order, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, s, i, now),
        )
    _sync_favorites_json(db, user_id, favs, None)
    return favorited, favs
