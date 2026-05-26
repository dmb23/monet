"""Kind classification (issue 06).

Three kinds: Expense, Income, Transfer. Sign rule first, then own-IBAN override.
Per ADR-0004, Kind is one of only two user-editable fields on a Transaction
(the other is Category) — but the *initial* assignment is fully deterministic.
"""

from __future__ import annotations

from typing import Iterable, Protocol


class _HasAmountAndCounterparty(Protocol):
    amount_cents: int
    counterparty_iban: str | None


EXPENSE = "Expense"
INCOME = "Income"
TRANSFER = "Transfer"


def _normalize_iban(iban: str | None) -> str:
    return (iban or "").replace(" ", "").upper()


class KindClassifier:
    """Pure-function classifier."""

    @staticmethod
    def classify(
        transaction: _HasAmountAndCounterparty,
        own_account_ibans: Iterable[str],
    ) -> str:
        own = {_normalize_iban(i) for i in own_account_ibans if i}
        cp = _normalize_iban(transaction.counterparty_iban)
        if cp and cp in own:
            return TRANSFER
        return INCOME if transaction.amount_cents > 0 else EXPENSE
