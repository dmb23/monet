"""Reconciliation Gate (ADR-0001).

`ReconciliationValidator.validate(result)` returns an `Outcome` carrying
either `ok=True` (commit all transactions) or `ok=False` with `diff_cents`
populated (commit none, write a `reconciliation_failed` sidecar).

Tolerance is fixed at €0.01 — see ADR-0001 on why this is binary, not a
threshold the caller gets to widen.
"""

from __future__ import annotations

from dataclasses import dataclass

from .extraction import ExtractionResult

TOLERANCE_CENTS = 1


@dataclass(frozen=True)
class Outcome:
    ok: bool
    expected_closing_cents: int
    computed_cents: int
    diff_cents: int
    transactions_extracted: int


def validate(result: ExtractionResult) -> Outcome:
    txn_sum = sum(t.amount_cents for t in result.transactions)
    computed = result.opening_balance_cents + txn_sum
    diff = computed - result.closing_balance_cents
    return Outcome(
        ok=abs(diff) <= TOLERANCE_CENTS,
        expected_closing_cents=result.closing_balance_cents,
        computed_cents=computed,
        diff_cents=diff,
        transactions_extracted=len(result.transactions),
    )
