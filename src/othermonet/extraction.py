"""Common contract every per-document-type parser conforms to.

`ExtractionResult` is the typed boundary between parsers and the rest of the
pipeline. Parsers may use whatever they like internally (camelot DataFrames,
regex over pdfminer text, …); the result they return must be this shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExtractedTransaction:
    booking_date: date
    value_date: date | None
    amount_cents: int  # signed: positive = credit, negative = debit
    description: str
    counterparty_iban: str | None
    counterparty_name: str | None


@dataclass(frozen=True)
class ExtractionResult:
    document_type: str
    iban: str
    period_start: date
    period_end: date
    opening_balance_cents: int
    closing_balance_cents: int
    transactions: list[ExtractedTransaction]


class Parser(Protocol):
    """Per-document-type parser contract.

    Implementations live as plain modules (no classes); they expose a
    `parse(pdf_path) -> ExtractionResult` function and a `DOCUMENT_TYPE`
    string constant. The dispatcher picks them up by name from accounts.toml.
    """

    DOCUMENT_TYPE: str

    def parse(self, pdf_path: Path) -> ExtractionResult: ...
