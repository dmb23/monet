"""Tests for accounts.toml loader and accounts-table reconciliation (issue 04)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import othermonet.db as db_module
from othermonet.db import get_db, init_db
from othermonet.registrations import (
    RegistrationError,
    load_registrations,
    match_registration,
    reconcile_accounts_table,
)


VALID_TWO_ACCOUNTS = """
[[account]]
filename_pattern = '^giro_.*\\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "DE00000000000000000001"
account_name     = "Triodos Girokonto"
owner_label      = "Anna"
bank_name        = "Triodos Bank"

[[account]]
filename_pattern = '^kk_.*\\.pdf$'
parser           = "triodos_kreditkarte"
iban             = "DE00000000000000000002"
account_name     = "Triodos Mastercard"
owner_label      = "Anna"
bank_name        = "Triodos Bank"
"""


def _write_toml(tmp: Path, body: str) -> Path:
    p = tmp / "accounts.toml"
    p.write_text(body)
    return p


# --- Loader unit tests --------------------------------------------------------


def test_load_valid_toml(tmp_path):
    path = _write_toml(tmp_path, VALID_TWO_ACCOUNTS)
    regs = load_registrations(path)
    assert [r.iban for r in regs] == [
        "DE00000000000000000001",
        "DE00000000000000000002",
    ]
    assert regs[0].document_type == "triodos.girokonto"
    assert regs[1].document_type == "triodos.kreditkarte"


def test_malformed_toml(tmp_path):
    path = _write_toml(tmp_path, "this is = = not valid toml [[[")
    with pytest.raises(RegistrationError, match="not valid TOML"):
        load_registrations(path)


def test_missing_required_field(tmp_path):
    path = _write_toml(
        tmp_path,
        """
[[account]]
filename_pattern = '^x_.*\\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "DE000000000000000001"
account_name     = "X"
# owner_label missing
bank_name        = "Y"
""",
    )
    with pytest.raises(RegistrationError, match="missing fields:.*owner_label"):
        load_registrations(path)


def test_duplicate_iban(tmp_path):
    path = _write_toml(
        tmp_path,
        """
[[account]]
filename_pattern = '^a_.*\\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "DE0000000000000000DUP"
account_name     = "A"
owner_label      = "Anna"
bank_name        = "B"

[[account]]
filename_pattern = '^b_.*\\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "DE0000000000000000DUP"
account_name     = "B"
owner_label      = "Anna"
bank_name        = "B"
""",
    )
    with pytest.raises(RegistrationError, match="duplicate IBAN"):
        load_registrations(path)


def test_invalid_regex(tmp_path):
    path = _write_toml(
        tmp_path,
        """
[[account]]
filename_pattern = '^(unclosed'
parser           = "triodos_kontoauszug"
iban             = "DE000000000000000003"
account_name     = "X"
owner_label      = "Anna"
bank_name        = "B"
""",
    )
    with pytest.raises(RegistrationError, match="invalid filename_pattern regex"):
        load_registrations(path)


def test_unknown_parser(tmp_path):
    path = _write_toml(
        tmp_path,
        """
[[account]]
filename_pattern = '^x_.*\\.pdf$'
parser           = "nope_not_a_parser"
iban             = "DE000000000000000004"
account_name     = "X"
owner_label      = "Anna"
bank_name        = "B"
""",
    )
    with pytest.raises(RegistrationError, match="unknown parser"):
        load_registrations(path)


def test_missing_file(tmp_path):
    with pytest.raises(RegistrationError, match="not found"):
        load_registrations(tmp_path / "does_not_exist.toml")


def test_no_entries(tmp_path):
    path = _write_toml(tmp_path, "# empty\n")
    with pytest.raises(RegistrationError, match="no \\[\\[account\\]\\]"):
        load_registrations(path)


def test_match_registration(tmp_path):
    regs = load_registrations(_write_toml(tmp_path, VALID_TWO_ACCOUNTS))
    assert match_registration("giro_2026-01.pdf", regs).iban.endswith("0001")
    assert match_registration("kk_2026-01.pdf", regs).iban.endswith("0002")
    assert match_registration("random.pdf", regs) is None


def test_example_toml_parses():
    """The checked-in example should be valid syntax (parser names + regex)."""
    regs = load_registrations(Path("accounts.toml.example"))
    assert {r.document_type for r in regs} == {
        "triodos.girokonto",
        "triodos.kreditkarte",
    }


# --- Reconciliation integration test ------------------------------------------


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()
    yield


def _accounts_rows():
    con = get_db()
    try:
        return {
            r[0]: r[1:]
            for r in con.execute(
                "SELECT iban, owner, account_name, bank_name FROM accounts"
            ).fetchall()
        }
    finally:
        con.close()


def test_reconcile_lifecycle(tmp_path, db):
    """Mirrors AC: two registrations → both rows inserted; edit owner_label →
    row updated; remove one registration → row preserved (no silent delete)."""
    path = _write_toml(tmp_path, VALID_TWO_ACCOUNTS)

    reconcile_accounts_table(load_registrations(path))
    rows = _accounts_rows()
    assert set(rows) == {"DE00000000000000000001", "DE00000000000000000002"}
    assert rows["DE00000000000000000001"] == ("Anna", "Triodos Girokonto", "Triodos Bank")

    edited = VALID_TWO_ACCOUNTS.replace("owner_label      = \"Anna\"", "owner_label      = \"Ben\"", 1)
    path.write_text(edited)
    reconcile_accounts_table(load_registrations(path))
    rows = _accounts_rows()
    assert rows["DE00000000000000000001"][0] == "Ben"
    assert rows["DE00000000000000000002"][0] == "Anna"

    reduced = """
[[account]]
filename_pattern = '^kk_.*\\.pdf$'
parser           = "triodos_kreditkarte"
iban             = "DE00000000000000000002"
account_name     = "Triodos Mastercard"
owner_label      = "Anna"
bank_name        = "Triodos Bank"
"""
    path.write_text(reduced)
    reconcile_accounts_table(load_registrations(path))
    rows = _accounts_rows()
    assert "DE00000000000000000001" in rows, "row for removed registration must be preserved"
    assert rows["DE00000000000000000001"][0] == "Ben"
