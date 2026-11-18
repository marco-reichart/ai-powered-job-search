"""Create a new empty job-search database from schema.sql."""

import argparse
import logging
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
logger = logging.getLogger(__name__)


def create_database(database_path: Path | str) -> Path:
    """Create an empty database from the project schema.

    Args:
        database_path (Path | str): Destination path, which must not exist.

    Returns:
        Resolved database path.
    """
    database_path = Path(database_path).expanduser().resolve()

    if database_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing database: {database_path}"
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = sqlite3.connect(database_path)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + schema_sql
            + "\nCOMMIT;"
        )
    except Exception:
        connection.rollback()
        connection.close()
        database_path.unlink(missing_ok=True)
        raise
    else:
        connection.close()

    return database_path


def main() -> None:
    """Run the database creation command-line interface."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Create a new, empty job-search SQLite database."
    )
    parser.add_argument(
        "database_path",
        type=Path,
        help="Output database path. It must not already exist.",
    )
    arguments = parser.parse_args()

    try:
        created_path = create_database(arguments.database_path)
    except (FileExistsError, OSError, sqlite3.Error) as error:
        parser.error(str(error))

    logger.info("Created empty database: %s", created_path)


if __name__ == "__main__":
    main()
