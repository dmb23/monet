"""Golden-file test for the Triodos Kontoauszug parser against a real PDF."""

from datetime import date

import pytest

from othermonet.reconciliation import validate
from othermonet.triodos_kontoauszug import DOCUMENT_TYPE, parse
from tests.fixtures import TRIODOS_GIRO_PDF, TRIODOS_SPARKONTO_PDF


@pytest.fixture(scope="module")
def giro():
    if not TRIODOS_GIRO_PDF.exists():
        pytest.skip(f"fixture missing: {TRIODOS_GIRO_PDF}")
    return parse(TRIODOS_GIRO_PDF)


@pytest.fixture(scope="module")
def sparkonto():
    if not TRIODOS_SPARKONTO_PDF.exists():
        pytest.skip(f"fixture missing: {TRIODOS_SPARKONTO_PDF}")
    return parse(TRIODOS_SPARKONTO_PDF)


def test_document_type(giro):
    assert giro.document_type == DOCUMENT_TYPE


def test_balances(giro):
    assert giro.period_start == date(2026, 3, 31)
    assert giro.period_end == date(2026, 4, 30)
    assert giro.opening_balance_cents == 524347
    assert giro.closing_balance_cents == 1323772


def test_reconciles(giro):
    assert validate(giro).ok


def test_transaction_count(giro):
    assert len(giro.transactions) == 25


def test_first_transaction(giro):
    first = giro.transactions[0]
    assert first.booking_date == date(2026, 4, 1)
    assert first.value_date == date(2026, 4, 1)
    assert first.amount_cents == -1955
    assert "HUK-COBURG" in first.description


def test_bsag_refund_is_credit(giro):
    matches = [t for t in giro.transactions if "BSAG" in t.description]
    assert len(matches) == 1
    assert matches[0].amount_cents == 1500


def test_large_straddled_credit(giro):
    big = [t for t in giro.transactions if t.amount_cents == 1_000_000]
    assert len(big) == 1
    assert "Erich und Sonja" in big[0].description


def test_counterparty_iban_extracted_when_present(giro):
    sepa = [t for t in giro.transactions if t.counterparty_iban]
    assert sepa, "expected at least one SEPA-style entry with a counterparty IBAN"
    for t in sepa:
        assert t.counterparty_iban.startswith(("DE", "FR", "NL", "LU", "BE", "AT", "IT", "ES"))


def test_sparkonto_reconciles(sparkonto):
    assert validate(sparkonto).ok


def test_sparkonto_balances(sparkonto):
    assert sparkonto.opening_balance_cents == 4045462
    assert sparkonto.closing_balance_cents == 4048945
