"""Golden-file test for the Triodos Kreditkarte parser against a real PDF."""

from datetime import date

import pytest

from othermonet.reconciliation import validate
from othermonet.triodos_kreditkarte import DOCUMENT_TYPE, parse
from tests.fixtures import TRIODOS_KREDITKARTE_PDF


@pytest.fixture(scope="module")
def statement():
    if not TRIODOS_KREDITKARTE_PDF.exists():
        pytest.skip(f"fixture missing: {TRIODOS_KREDITKARTE_PDF}")
    return parse(TRIODOS_KREDITKARTE_PDF)


def test_document_type(statement):
    assert statement.document_type == DOCUMENT_TYPE


def test_period(statement):
    assert statement.period_start == date(2026, 3, 14)
    assert statement.period_end == date(2026, 4, 15)


def test_balances(statement):
    assert statement.opening_balance_cents == 17972
    assert statement.closing_balance_cents == -99712


def test_reconciles(statement):
    assert validate(statement).ok, "kreditkarte statement must reconcile within €0.01"


def test_gutschrift_is_credit(statement):
    credits = [t for t in statement.transactions if t.amount_cents > 0]
    assert any(t.amount_cents == 60000 for t in credits), (
        "expected the 600,00+ Gutschrift auf Karte as a positive amount"
    )


def test_auslandseinsatzentgelt_is_attached_as_fee(statement):
    fees = [t for t in statement.transactions if t.counterparty_name == "Auslandseinsatzentgelt"]
    assert len(fees) >= 1
    for f in fees:
        assert f.amount_cents < 0


def test_no_uebertrag_or_zwischensaldo_leaked(statement):
    for t in statement.transactions:
        assert "Übertrag" not in t.description
        assert "Zwischensaldo" not in t.description
