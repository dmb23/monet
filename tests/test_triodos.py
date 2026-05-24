"""End-to-end test for Triodos PDF extraction against a real fixture statement."""

from datetime import date
from pathlib import Path

import pytest

from othermonet.triodos import extract_statement


FIXTURE = (
    Path(__file__).parent.parent
    / "data"
    / "1032455006_2026_Nr.004_Kontoauszug_vom_2026.05.01_20260506122148.pdf"
)


@pytest.fixture(scope="module")
def statement():
    if not FIXTURE.exists():
        pytest.skip(f"fixture PDF missing: {FIXTURE}")
    return extract_statement(FIXTURE)


def test_balances(statement):
    assert statement.opening.on == date(2026, 3, 31)
    assert statement.opening.amount_cents == 524347
    assert statement.closing.on == date(2026, 4, 30)
    assert statement.closing.amount_cents == 1323772


def test_reconciles(statement):
    assert statement.reconciles(), (
        f"opening {statement.opening.amount_cents} + "
        f"sum {int(statement.transactions['amount_cents'].sum())} "
        f"!= closing {statement.closing.amount_cents}"
    )


def test_transaction_count(statement):
    assert len(statement.transactions) == 25


def test_first_transaction(statement):
    first = statement.transactions.iloc[0]
    assert first["booking_date"] == date(2026, 4, 1)
    assert first["value_date"] == date(2026, 4, 1)
    assert first["vorgang_type"] == "Lastschrift"
    assert first["amount_cents"] == -1955
    assert "HUK-COBURG" in first["description"]
    assert "UNFA" in first["description"]
    assert "VRK VVAG" in first["description"]


def test_bsag_refund_is_credit(statement):
    """The 09.04 BSAG Reklamation row is a +15.00 EUR credit (Haben), not a debit."""
    txns = statement.transactions
    bsag = txns[txns["description"].str.contains("BSAG", na=False)]
    assert len(bsag) == 1
    assert bsag.iloc[0]["amount_cents"] == 1500
    assert bsag.iloc[0]["booking_date"] == date(2026, 4, 9)


def test_large_credit_straddling_columns(statement):
    """The 21.04 SEPA-Überweisung 10.000,00 H may straddle Soll/Haben columns."""
    txns = statement.transactions
    big = txns[txns["amount_cents"] == 1_000_000]
    assert len(big) == 1
    assert big.iloc[0]["booking_date"] == date(2026, 4, 21)
    assert "Erich und Sonja" in big.iloc[0]["description"]


def test_dataflowz_salary(statement):
    txns = statement.transactions
    salary = txns[txns["description"].str.contains("Dataflowz", na=False)]
    assert len(salary) == 1
    assert salary.iloc[0]["amount_cents"] == 415705
    assert salary.iloc[0]["vorgang_type"] == "Überweisungsgutschr."


def test_no_uebertrag_rows_leaked_through(statement):
    txns = statement.transactions
    assert not txns["description"].str.contains("Übertrag", na=False).any()
    assert not txns["vorgang_type"].str.contains("Übertrag", na=False).any()


def test_value_date_parsed_for_every_row(statement):
    txns = statement.transactions
    assert txns["value_date"].notna().all()
    assert txns["booking_date"].notna().all()
