"""Dashboard HTTP tests for Kind override + totals exclusion (issue 06)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

import othermonet.app as app_module
import othermonet.db as db_module
from othermonet.fingerprint import Fingerprinter


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
        # Lifespan calls load_registrations(); give it a valid (no-op) config.
        toml_path = tmp_path / "accounts.toml"
        toml_path.write_text(_MINIMAL_TOML)
        monkeypatch.setenv("OTHERMONET_ACCOUNTS_TOML", str(toml_path))
        monkeypatch.setenv("OTHERMONET_INBOX", str(tmp_path / "inbox"))
        (tmp_path / "inbox").mkdir()
        db_module.init_db()
        con = db_module.get_db()
        try:
            account_id = con.execute(
                "INSERT INTO accounts (iban, owner) VALUES (?, ?) RETURNING id",
                ["DE_GIRO", "T"],
            ).fetchone()[0]
            for booking, amount, desc, kind in [
                ("2026-01-05", 200000, "Salary", "Income"),
                ("2026-01-10", -1250, "EDEKA", "Expense"),
                ("2026-01-15", -50000, "To savings", "Transfer"),
            ]:
                con.execute(
                    """INSERT INTO transactions
                          (account_id, fingerprint, booking_date, amount_cents,
                           description, kind)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        account_id,
                        Fingerprinter.fingerprint(account_id, booking, amount, desc),
                        booking,
                        amount,
                        desc,
                        kind,
                    ],
                )
        finally:
            con.close()
        with TestClient(app_module.app) as c:
            yield c


def test_dashboard_totals_exclude_transfer(client):
    body = client.get("/").text
    assert "2000.00€" in body
    assert "12.50€" in body
    # Transfer row exists but does NOT appear in totals math.
    assert "To savings" in body
    # Quick sanity check that net = income - spend.
    assert "1987.50€" in body


def test_kind_override_persists(client):
    txn_id = _expense_id()
    resp = client.post(
        f"/transactions/{txn_id}/kind",
        data={"kind": "Transfer"},
    )
    assert resp.status_code == 200
    assert f'id="txn-{txn_id}"' in resp.text
    # Reload the dashboard and confirm the override persisted.
    body = client.get("/").text
    # Spend total now drops to 0 because the only expense was reclassified.
    assert "0.00€" in body


def test_kind_override_rejects_invalid_value(client):
    txn_id = _expense_id()
    resp = client.post(f"/transactions/{txn_id}/kind", data={"kind": "Nope"})
    assert resp.status_code == 400


def test_kind_override_404_for_unknown_id(client):
    resp = client.post("/transactions/999999/kind", data={"kind": "Expense"})
    assert resp.status_code == 404


def _expense_id() -> int:
    con = db_module.get_db()
    try:
        return con.execute(
            "SELECT id FROM transactions WHERE description = 'EDEKA'"
        ).fetchone()[0]
    finally:
        con.close()
