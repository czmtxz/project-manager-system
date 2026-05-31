# -*- coding: utf-8 -*-
"""为 project_participants 增加 (project_id, participant_id) 唯一约束并去重（可重复执行）。

背景：原表无唯一约束，project_participant_add 使用 INSERT OR REPLACE 时无法真正替换，
会产生重复行，导致投资/分红比例汇总重复计算。本迁移先合并重复行，再建唯一索引。
"""
import os
import sqlite3

DB = os.environ.get('DATABASE', 'project_manager.db')


def dedupe(conn):
    groups = conn.execute(
        """SELECT project_id, participant_id, COUNT(*) AS c
           FROM project_participants
           GROUP BY project_id, participant_id
           HAVING c > 1"""
    ).fetchall()
    merged = 0
    for project_id, participant_id, _c in groups:
        rows = conn.execute(
            """SELECT id, project_role, investment_ratio, dividend_ratio
               FROM project_participants
               WHERE project_id=? AND participant_id=?
               ORDER BY id""",
            (project_id, participant_id)
        ).fetchall()
        keep_id = rows[-1][0]  # 保留最新一条
        max_inv = max((r[2] or 0) for r in rows)
        max_div = max((r[3] or 0) for r in rows)
        role = 'member'
        for r in rows:
            if r[1] and r[1] != 'member':
                role = r[1]
                break
        conn.execute(
            """UPDATE project_participants
               SET investment_ratio=?, dividend_ratio=?, project_role=?
               WHERE id=?""",
            (max_inv, max_div, role, keep_id)
        )
        conn.execute(
            """DELETE FROM project_participants
               WHERE project_id=? AND participant_id=? AND id<>?""",
            (project_id, participant_id, keep_id)
        )
        merged += 1
    return merged


def main():
    conn = sqlite3.connect(DB)
    try:
        merged = dedupe(conn)
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_pp_project_participant
               ON project_participants(project_id, participant_id)"""
        )
        conn.commit()
        print('project_participant unique ok (merged %d duplicate groups)' % merged)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
