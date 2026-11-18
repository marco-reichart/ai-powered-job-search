import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
configured_db_path = Path(os.environ.get("JOB_SEARCH_DB_PATH", "data/job_search.db")).expanduser()
DB_PATH = configured_db_path if configured_db_path.is_absolute() else PROJECT_ROOT / configured_db_path


@contextmanager
def get_db_connection() -> Iterator[sqlite3.Connection]:
    """Yield a database connection and manage its transaction.

    Yields:
        SQLite connection with row access enabled.
    """
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def initialize_database() -> Path:
    """Check that the configured database is accessible.

    Returns:
        Configured database path.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    with get_db_connection() as connection:
        connection.execute("SELECT 1")

    return DB_PATH
