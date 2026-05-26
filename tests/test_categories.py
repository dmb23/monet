"""Category CRUD + Uncategorized protection (issue 07)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

import othermonet.app as app_module
import othermonet.db as db_module
from othermonet.fingerprint import Fingerprinter
from othermonet.seed import STARTER_CATEGORIES, UNCATEGORIZED


_MINIMAL_TOML = """
[[account]]
filename_pattern = '^never-matches\\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "DE_GIRO"
account_name     = "Giro"
owner_label      = "T"
bank_name        = "B"
"""


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
        toml_path = tmp_path / "accounts.toml"
        toml_path.write_text(_MINIMAL_TOML)
        monkeypatch.setenv("OTHERMONET_ACCOUNTS_TOML", str(toml_path))
        monkeypatch.setenv("OTHERMONET_INBOX", str(tmp_path / "inbox"))
        (tmp_path / "inbox").mkdir()
        db_module.init_db()
        with TestClient(app_module.app) as c:
            yield c


def _names() -> list[str]:
    con = db_module.get_db()
    try:
        return [r[0] for r in con.execute("SELECT name FROM categories ORDER BY name").fetchall()]
    finally:
        con.close()


def test_first_boot_seeds_starter_categories(client):
    names = set(_names())
    assert UNCATEGORIZED in names
    for c in STARTER_CATEGORIES:
        assert c in names


def test_seed_is_idempotent_across_restarts(client):
    # Hitting the app twice (a single TestClient context = one lifespan).
    # Inspect the state after the second seed call directly.
    from othermonet.seed import seed_categories

    before = _names()
    seed_categories()
    after = _names()
    assert before == after


def test_list_page_renders(client):
    body = client.get("/categories").text
    assert "Categories" in body
    for c in STARTER_CATEGORIES:
        assert c in body
    assert "locked" in body  # Uncategorized rendered as locked


def test_create_category(client):
    resp = client.post("/categories", data={"name": "Gym"})
    assert resp.status_code == 200
    assert "Gym" in _names()


def test_create_rejects_empty_name(client):
    resp = client.post("/categories", data={"name": "   "})
    assert resp.status_code == 400


def test_create_rejects_duplicate(client):
    client.post("/categories", data={"name": "Gym"})
    resp = client.post("/categories", data={"name": "Gym"})
    assert resp.status_code == 409


def test_rename_category(client):
    client.post("/categories", data={"name": "Gym"})
    cat_id = _id_of("Gym")
    resp = client.post(
        f"/categories/{cat_id}/rename", data={"name": "Sports"}
    )
    assert resp.status_code == 200
    assert "Gym" not in _names()
    assert "Sports" in _names()


def test_rename_uncategorized_rejected(client):
    cat_id = _id_of(UNCATEGORIZED)
    resp = client.post(
        f"/categories/{cat_id}/rename", data={"name": "Anything"}
    )
    assert resp.status_code == 400
    assert UNCATEGORIZED in _names()


def test_delete_category(client):
    client.post("/categories", data={"name": "TempCat"})
    cat_id = _id_of("TempCat")
    resp = client.post(f"/categories/{cat_id}/delete")
    assert resp.status_code == 200
    assert "TempCat" not in _names()


def test_delete_uncategorized_rejected(client):
    cat_id = _id_of(UNCATEGORIZED)
    resp = client.post(f"/categories/{cat_id}/delete")
    assert resp.status_code == 400
    assert UNCATEGORIZED in _names()


def test_delete_detaches_transactions(client):
    """A transaction pointing at the deleted category should fall back to NULL,
    not break the FK."""
    client.post("/categories", data={"name": "Bowling"})
    cat_id = _id_of("Bowling")

    con = db_module.get_db()
    try:
        account_id = con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?) RETURNING id",
            ["DE_TEST", "T"],
        ).fetchone()[0]
        fp = Fingerprinter.fingerprint(account_id, "2026-01-05", -1000, "x")
        txn_id = con.execute(
            """INSERT INTO transactions
                  (account_id, fingerprint, booking_date, amount_cents,
                   description, kind, category_id)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            [account_id, fp, "2026-01-05", -1000, "x", "Expense", cat_id],
        ).fetchone()[0]
    finally:
        con.close()

    resp = client.post(f"/categories/{cat_id}/delete")
    assert resp.status_code == 200

    con = db_module.get_db()
    try:
        cat_after = con.execute(
            "SELECT category_id FROM transactions WHERE id = ?", [txn_id]
        ).fetchone()[0]
    finally:
        con.close()
    assert cat_after is None


def test_assign_category_to_transaction(client):
    cat_id = _id_of("Groceries")
    con = db_module.get_db()
    try:
        account_id = con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?) RETURNING id",
            ["DE_ASSIGN", "T"],
        ).fetchone()[0]
        fp = Fingerprinter.fingerprint(account_id, "2026-01-05", -1000, "edeka")
        txn_id = con.execute(
            """INSERT INTO transactions
                  (account_id, fingerprint, booking_date, amount_cents,
                   description, kind)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            [account_id, fp, "2026-01-05", -1000, "edeka", "Expense"],
        ).fetchone()[0]
    finally:
        con.close()

    resp = client.post(
        f"/transactions/{txn_id}/category", data={"category_id": str(cat_id)}
    )
    assert resp.status_code == 200

    con = db_module.get_db()
    try:
        stored = con.execute(
            "SELECT category_id FROM transactions WHERE id = ?", [txn_id]
        ).fetchone()[0]
    finally:
        con.close()
    assert stored == cat_id


def _id_of(name: str) -> int:
    con = db_module.get_db()
    try:
        return con.execute(
            "SELECT id FROM categories WHERE name = ?", [name]
        ).fetchone()[0]
    finally:
        con.close()
