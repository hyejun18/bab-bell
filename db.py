"""Database module for BabBell bot using SQLite."""

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from config import SQLITE_PATH

# Thread-local storage for connections
_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Get thread-local database connection."""
    if not hasattr(_local, "connection"):
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.connection = conn
    return _local.connection


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context manager for database connection."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Initialize database schema."""
    with get_db() as conn:
        # users table - now with workspace_id
        # Primary key is (workspace_id, slack_user_id) to support multi-workspace
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                workspace_id    TEXT NOT NULL DEFAULT 'default',
                slack_user_id   TEXT NOT NULL,
                slack_name      TEXT,
                display_name    TEXT,
                real_name       TEXT,
                dm_channel_id   TEXT,
                is_subscribed   INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY (workspace_id, slack_user_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(is_subscribed)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_workspace ON users(workspace_id)"
        )

        # send_log table - now with workspace_id
        conn.execute("""
            CREATE TABLE IF NOT EXISTS send_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id    TEXT NOT NULL DEFAULT 'default',
                broadcast_id    TEXT NOT NULL,
                action          TEXT NOT NULL,
                initiated_by    TEXT NOT NULL,
                target_user_id  TEXT NOT NULL,
                dm_channel_id   TEXT,
                dm_ts           TEXT,
                ok              INTEGER NOT NULL,
                error           TEXT,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_send_log_broadcast ON send_log(broadcast_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_send_log_target_time ON send_log(target_user_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_send_log_ok_time ON send_log(ok, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_send_log_workspace ON send_log(workspace_id)"
        )

        # Poll tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                poll_id     TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                closed_at   TEXT
            )
        """)

        # poll_messages - now with workspace_id (same user_id can exist in multiple workspaces)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS poll_messages (
                poll_id      TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT 'default',
                user_id      TEXT NOT NULL,
                channel_id   TEXT NOT NULL,
                message_ts   TEXT NOT NULL,
                PRIMARY KEY (poll_id, workspace_id, user_id),
                FOREIGN KEY(poll_id) REFERENCES polls(poll_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_poll_messages_poll ON poll_messages(poll_id)"
        )

        # poll_votes - workspace_id needed for user identification
        # Note: votes aggregate across workspaces (same poll_id), so user is (workspace_id, user_id)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id         TEXT NOT NULL,
                workspace_id    TEXT NOT NULL DEFAULT 'default',
                user_id         TEXT NOT NULL,
                restaurant_name TEXT NOT NULL,
                voted_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY (poll_id, workspace_id, user_id, restaurant_name),
                FOREIGN KEY(poll_id) REFERENCES polls(poll_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_poll_votes_poll ON poll_votes(poll_id)"
        )


def migrate_db() -> None:
    """Migrate existing database to support multi-workspace.

    Adds workspace_id column to existing tables if they don't have it.
    """
    with get_db() as conn:
        # Check if migration is needed by checking users table schema
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in cursor.fetchall()}

        if "workspace_id" not in columns:
            # Migration needed - add workspace_id to existing tables
            conn.execute("ALTER TABLE users ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")

        # Check send_log
        cursor = conn.execute("PRAGMA table_info(send_log)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "workspace_id" not in columns:
            conn.execute("ALTER TABLE send_log ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")

        # Check poll_messages
        cursor = conn.execute("PRAGMA table_info(poll_messages)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "workspace_id" not in columns:
            conn.execute("ALTER TABLE poll_messages ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")

        # Check poll_votes
        cursor = conn.execute("PRAGMA table_info(poll_votes)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "workspace_id" not in columns:
            conn.execute("ALTER TABLE poll_votes ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")


@dataclass
class User:
    """User data class."""

    workspace_id: str
    slack_user_id: str
    slack_name: str | None
    display_name: str | None
    real_name: str | None
    dm_channel_id: str | None
    is_subscribed: bool
    created_at: str
    updated_at: str


def get_subscribed_users(workspace_id: str | None = None) -> list[User]:
    """Get all subscribed users.

    Args:
        workspace_id: If provided, filter by workspace. If None, return all.
    """
    with get_db() as conn:
        if workspace_id:
            cursor = conn.execute(
                "SELECT * FROM users WHERE is_subscribed = 1 AND workspace_id = ?",
                (workspace_id,),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM users WHERE is_subscribed = 1"
            )
        rows = cursor.fetchall()
        return [
            User(
                workspace_id=row["workspace_id"],
                slack_user_id=row["slack_user_id"],
                slack_name=row["slack_name"],
                display_name=row["display_name"],
                real_name=row["real_name"],
                dm_channel_id=row["dm_channel_id"],
                is_subscribed=bool(row["is_subscribed"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


def get_user(workspace_id: str, slack_user_id: str) -> User | None:
    """Get user by workspace and Slack user ID."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE workspace_id = ? AND slack_user_id = ?",
            (workspace_id, slack_user_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return User(
            workspace_id=row["workspace_id"],
            slack_user_id=row["slack_user_id"],
            slack_name=row["slack_name"],
            display_name=row["display_name"],
            real_name=row["real_name"],
            dm_channel_id=row["dm_channel_id"],
            is_subscribed=bool(row["is_subscribed"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def upsert_user(
    workspace_id: str,
    slack_user_id: str,
    slack_name: str | None = None,
    display_name: str | None = None,
    real_name: str | None = None,
    dm_channel_id: str | None = None,
    is_subscribed: bool = True,
) -> None:
    """Insert or update a user (opt-in on DM)."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users (workspace_id, slack_user_id, slack_name, display_name, real_name, dm_channel_id, is_subscribed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, slack_user_id) DO UPDATE SET
                slack_name = COALESCE(excluded.slack_name, slack_name),
                display_name = COALESCE(excluded.display_name, display_name),
                real_name = COALESCE(excluded.real_name, real_name),
                dm_channel_id = COALESCE(excluded.dm_channel_id, dm_channel_id),
                is_subscribed = excluded.is_subscribed,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (workspace_id, slack_user_id, slack_name, display_name, real_name, dm_channel_id, int(is_subscribed)),
        )


def update_user_dm_channel(workspace_id: str, slack_user_id: str, dm_channel_id: str) -> None:
    """Update user's cached DM channel ID."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users SET dm_channel_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE workspace_id = ? AND slack_user_id = ?
            """,
            (dm_channel_id, workspace_id, slack_user_id),
        )


def unsubscribe_user(workspace_id: str, slack_user_id: str) -> None:
    """Unsubscribe a user (opt-out)."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users SET is_subscribed = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE workspace_id = ? AND slack_user_id = ?
            """,
            (workspace_id, slack_user_id),
        )


def insert_send_log(
    workspace_id: str,
    broadcast_id: str,
    action: str,
    initiated_by: str,
    target_user_id: str,
    dm_channel_id: str | None,
    dm_ts: str | None,
    ok: bool,
    error: str | None,
) -> None:
    """Insert a send log entry."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO send_log (workspace_id, broadcast_id, action, initiated_by, target_user_id, dm_channel_id, dm_ts, ok, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, broadcast_id, action, initiated_by, target_user_id, dm_channel_id, dm_ts, int(ok), error),
        )


# Future extension: broadcast metadata for web aggregation
@dataclass
class BroadcastMeta:
    """Metadata for a single broadcast event (for future web aggregation)."""

    broadcast_id: str
    action: str
    initiated_by: str
    created_at: str
    menu_data: dict | None  # Structured menu data


def create_broadcast_metadata(
    broadcast_id: str,
    action: str,
    initiated_by: str,
    menu_data: dict | None = None,
) -> BroadcastMeta:
    """Create broadcast metadata (for future web aggregation page).

    This function is separated to allow easy integration with a future
    web-based aggregation page that can query broadcasts by ID.
    """
    from datetime import datetime, timezone

    return BroadcastMeta(
        broadcast_id=broadcast_id,
        action=action,
        initiated_by=initiated_by,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        menu_data=menu_data,
    )
