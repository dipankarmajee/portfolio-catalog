"""
core/database.py
Unified SQLite database management, connection pooling, and schema documentation.
"""

from contextlib import contextmanager
import logging
from pathlib import Path
import sqlite3
from typing import Generator, List, Tuple

from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


def get_connection(db_path: Path) -> sqlite3.Connection:
    """
    Creates an optimized SQLite connection with WAL mode and sensible timeouts.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode and normal synchronous for performant and safe file operations
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
    except sqlite3.OperationalError:
        pass
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """
    Context manager for atomic SQLite transactions. Automatically commits or rolls back.
    """
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Transaction failed and was rolled back: %s", e)
        raise DatabaseError(f"Transaction failed: {e}") from e


def register_schema_documentation(
    conn: sqlite3.Connection,
    table_name: str,
    column_definitions: List[Tuple[str, str, int, str]],
):
    """
    Registers human-readable column documentation in the _schema_documentation table.
    Tuple structure: (column_name, data_type, is_primary_key, description)
    """
    with transaction(conn) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS _schema_documentation (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                data_type TEXT NOT NULL,
                is_primary_key INTEGER NOT NULL,
                description TEXT NOT NULL,
                PRIMARY KEY (table_name, column_name)
            )
        """)
        cursor.executemany("""
            INSERT OR REPLACE INTO _schema_documentation 
            (table_name, column_name, data_type, is_primary_key, description)
            VALUES (?, ?, ?, ?, ?)
        """, [(table_name, col, dt, pk, desc) for col, dt, pk, desc in column_definitions])

