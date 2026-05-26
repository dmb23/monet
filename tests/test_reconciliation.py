"""Table-driven tests for the Reconciliation Gate (ADR-0001)."""

from datetime import date

import pytest

from othermonet.extraction import ExtractedTransaction, ExtractionResult
from othermonet.reconciliation import validate


def _txn(amount: int) -> ExtractedTransaction:
    return ExtractedTransaction(
        booking_date=date(2026, 1, 1),
        value_date=None,
        amount_cents=amount,
        description="x",
        counterparty_iban=None,
        counterparty_name=None,
    )


def _result(opening: int, closing: int, txns: list[int]) -> ExtractionResult:
    return ExtractionResult(
        document_type="t",
        iban="DE00",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        transactions=[_txn(a) for a in txns],
    )


@pytest.mark.parametrize(
    "name,opening,closing,txns,expect_ok",
    [
        ("balanced", 10000, 9000, [-1000], True),
        ("balanced_empty", 10000, 10000, [], True),
        ("off_by_1_cent_within_tolerance", 10000, 9000, [-999], True),
        ("off_by_2_cents", 10000, 9000, [-998], False),
        ("off_by_one_euro", 10000, 9000, [-2000], False),
        ("sign_flipped_row", 10000, 6000, [1000, -3000], False),  # actual was [-1000,-3000]
        ("missing_row", 10000, 6000, [-1000, -3000, -500], False),
        ("balanced_with_credits", 0, 5000, [10000, -5000], True),
    ],
)
def test_validator(name, opening, closing, txns, expect_ok):
    outcome = validate(_result(opening, closing, txns))
    assert outcome.ok is expect_ok, (
        f"{name}: diff_cents={outcome.diff_cents}, expected ok={expect_ok}"
    )
    assert outcome.transactions_extracted == len(txns)
