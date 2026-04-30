"""Smoke tests for the database schema and basic operations."""

import pytest
import duckdb
from pathlib import Path
from tempfile import TemporaryDirectory

from othermonet.db import init_db, get_db
from othermonet.seed import seed, compute_fingerprint
from othermonet.schema import SCHEMA_SQL


def test_schema_tables_exist():
    """Test that all v1 tables are created."""
    with TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test.db"
        con = duckdb.connect(str(test_db_path))
        con.execute(SCHEMA_SQL)

        tables = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = [t[0] for t in tables]

        expected_tables = [
            "accounts",
            "statements",
            "transactions",
            "categories",
            "merchant_memory",
            "category_history",
        ]
        for table in expected_tables:
            assert table in table_names, f"Table {table} not found in schema"

        con.close()


def test_transaction_roundtrip():
    """Test that we can insert and retrieve a Transaction row."""
    with TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test.db"
        con = duckdb.connect(str(test_db_path))
        con.execute(SCHEMA_SQL)

        account_id = con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?) RETURNING id",
            ["DE89370400440532013000", "Test Owner"],
        ).fetchone()[0]

        fingerprint = compute_fingerprint(account_id, "2024-01-15", -1250, "Test Transaction")
        con.execute(
            """INSERT INTO transactions
               (account_id, fingerprint, booking_date, amount_cents, description,
                counterparty_iban, counterparty_name, kind, category_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                account_id,
                fingerprint,
                "2024-01-15",
                -1250,
                "Test Transaction",
                "DE12345678901234567890",
                "Test Counterparty",
                "Expense",
                None,
            ],
        )

        result = con.execute(
            """SELECT fingerprint, booking_date, amount_cents, description
               FROM transactions WHERE fingerprint = ?""",
            [fingerprint],
        ).fetchone()

        assert result is not None
        assert result == (fingerprint, "2024-01-15", -1250, "Test Transaction")

        con.close()


def test_seed_creates_account_and_transactions():
    """Test that the seed script creates data."""
    with TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test.db"
        import othermonet.db as db_module

        original_db_path = db_module.DB_PATH
        db_module.DB_PATH = Path(test_db_path)

        try:
            db_module.init_db()
            seed()

            con = db_module.get_db()
            accounts = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            transactions = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

            assert accounts == 1, f"Expected 1 account, got {accounts}"
            assert transactions == 4, f"Expected 4 transactions, got {transactions}"
            con.close()
        finally:
            db_module.DB_PATH = original_db_path
