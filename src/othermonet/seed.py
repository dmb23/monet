"""Seed the database with sample data for development."""

import hashlib
from .db import get_db


def compute_fingerprint(account_id, booking_date, amount_cents, description):
    """Compute a deterministic fingerprint for a transaction."""
    normalized = f"{account_id}:{booking_date}:{amount_cents}:{description.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def seed_if_empty():
    """Seed only if the accounts table is empty (idempotent across restarts)."""
    con = get_db()
    try:
        already_seeded = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] > 0
    finally:
        con.close()
    if already_seeded:
        return
    seed()


def seed():
    """Seed the database with one Account and several Transactions."""
    con = get_db()

    account_id = con.execute(
        "INSERT INTO accounts (iban, owner) VALUES (?, ?) RETURNING id",
        ["DE89370400440532013000", "Mischa"],
    ).fetchone()[0]

    transactions = [
        {
            "account_id": account_id,
            "booking_date": "2024-01-15",
            "amount_cents": -1250,
            "description": "EDEKA Nordhorn",
            "counterparty_iban": "DE12345678901234567890",
            "counterparty_name": "EDEKA Nordhorn",
            "kind": "Expense",
            "category_id": None,
        },
        {
            "account_id": account_id,
            "booking_date": "2024-01-18",
            "amount_cents": -4500,
            "description": "REWE City",
            "counterparty_iban": "DE09876543210987654321",
            "counterparty_name": "REWE City",
            "kind": "Expense",
            "category_id": None,
        },
        {
            "account_id": account_id,
            "booking_date": "2024-01-22",
            "amount_cents": 120000,
            "description": "Salary Jan 2024",
            "counterparty_iban": "DE11111111111111111111",
            "counterparty_name": "Employer GmbH",
            "kind": "Income",
            "category_id": None,
        },
        {
            "account_id": account_id,
            "booking_date": "2024-01-25",
            "amount_cents": -8900,
            "description": "Monthly Rent",
            "counterparty_iban": "DE22222222222222222222",
            "counterparty_name": "Landlord",
            "kind": "Expense",
            "category_id": None,
        },
    ]

    for txn in transactions:
        fingerprint = compute_fingerprint(
            txn["account_id"],
            txn["booking_date"],
            txn["amount_cents"],
            txn["description"],
        )
        con.execute(
            """INSERT INTO transactions
               (account_id, fingerprint, booking_date, amount_cents, description,
                counterparty_iban, counterparty_name, kind, category_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                txn["account_id"],
                fingerprint,
                txn["booking_date"],
                txn["amount_cents"],
                txn["description"],
                txn["counterparty_iban"],
                txn["counterparty_name"],
                txn["kind"],
                txn["category_id"],
            ],
        )

    con.close()
    print(f"Seeded {len(transactions)} transactions for account {account_id}")


if __name__ == "__main__":
    from . import db

    db.init_db()
    seed_if_empty()
