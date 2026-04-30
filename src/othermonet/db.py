import duckdb
from pathlib import Path

from .schema import SCHEMA_SQL

DB_PATH = Path("data/expenses.db")


def get_db():
    """Get a DuckDB connection to the expenses database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET enable_progress_bar = false")
    return con


def init_db():
    """Initialize the database schema if it doesn't exist."""
    con = get_db()
    con.execute(SCHEMA_SQL)
    con.close()
