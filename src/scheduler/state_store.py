"""
增量推送状态存储模块。

用 SQLite 记录"某个订阅任务已经推送过哪些内容指纹"，
每次定时任务触发时，先查询已推送记录，只保留新增内容再生成文档，
避免赛题要求中提到的"重复推送"问题。
"""

import sqlite3
from pathlib import Path
from typing import List, Set

DB_PATH = Path("data/pushed_state.db")


def _get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pushed_items (
            subscription_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            pushed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (subscription_id, fingerprint)
        )
    """)
    return conn


def get_pushed_fingerprints(subscription_id: str) -> Set[str]:
    """获取某个订阅任务（对应一个用户问题）历史上已推送过的指纹集合。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT fingerprint FROM pushed_items WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def mark_as_pushed(subscription_id: str, fingerprints: List[str]) -> None:
    conn = _get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO pushed_items (subscription_id, fingerprint) VALUES (?, ?)",
        [(subscription_id, fp) for fp in fingerprints],
    )
    conn.commit()
    conn.close()


def make_subscription_id(raw_query: str) -> str:
    """
    用原始用户问题生成订阅任务的唯一 ID。
    同一个问题多次触发（定时任务的每一次执行）应视为同一个订阅，
    共享同一份"已推送"记录。
    """
    import hashlib
    return hashlib.md5(raw_query.strip().encode("utf-8")).hexdigest()[:16]
