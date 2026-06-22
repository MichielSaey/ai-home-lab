import os
import sqlite3
from typing import Any, Dict, Optional

DEFAULT_DB_PATH = os.environ.get("DB_PATH", "data/ai_home_lab.db")


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            goals TEXT,
            injuries TEXT,
            garmin_username TEXT,
            garmin_password_enc TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def get_user_profile(user_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT user_id, goals, injuries, garmin_username, garmin_password_enc FROM user_profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def upsert_user_profile(
    user_id: str,
    goals: str,
    injuries: str,
    garmin_username: str,
    garmin_password_enc: str,
    db_path: Optional[str] = None,
) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO user_profiles (user_id, goals, injuries, garmin_username, garmin_password_enc, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            goals = excluded.goals,
            injuries = excluded.injuries,
            garmin_username = excluded.garmin_username,
            garmin_password_enc = excluded.garmin_password_enc,
            updated_at = excluded.updated_at
        """,
        (user_id, goals, injuries, garmin_username, garmin_password_enc),
    )
    conn.commit()
