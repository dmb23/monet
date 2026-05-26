"""KindClassifier table-driven tests + integration test (issue 06)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import othermonet.db as db_module
from othermonet.extraction import ExtractedTransaction, ExtractionResult
from othermonet.extractor import ingest_pdf
from othermonet.kind import EXPENSE, INCOME, TRANSFER, KindClassifier
from othermonet.registrations import Registration
import re


@dataclass
class _Txn:
    amount_cents: int
    counterparty_iban: str | None


OWN = {"DE89370400440532013000", "DE12345678901234567890"}


@pytest.mark.parametrize(
    "txn, expected",
    [
        # Sign rule: positive = Income.
        (_Txn(amount_cents=12000, counterparty_iban=None), INCOME),
        # Sign rule: negative = Expense.
        (_Txn(amount_cents=-1250, counterparty_iban=None), EXPENSE),
        # IBAN match overrides sign (positive incoming transfer from own account).
        (_Txn(amount_cents=50000, counterparty_iban="DE89370400440532013000"), TRANSFER),
        # IBAN match overrides sign (outgoing transfer to own account).
        (_Txn(amount_cents=-50000, counterparty_iban="DE12345678901234567890"), TRANSFER),
        # IBAN present but not in own_ibans → falls through to sign rule.
        (_Txn(amount_cents=-50000, counterparty_iban="DE99999999999999999999"), EXPENSE),
        # IBAN match is case- and whitespace-insensitive.
        (_Txn(amount_cents=-1, counterparty_iban="de89 3704 0044 0532 0130 00"), TRANSFER),
        # No counterparty IBAN extracted → sign rule.
        (_Txn(amount_cents=-1, counterparty_iban=""), EXPENSE),
    ],
)
def test_classify(txn, expected):
    assert KindClassifier.classify(txn, OWN) == expected


def test_classify_empty_own_ibans():
    assert (
        KindClassifier.classify(_Txn(-1, "DE89370400440532013000"), [])
        == EXPENSE
    )


# ---- Integration: a Transfer leg between two own accounts -------------------


class _StubParser:
    DOCUMENT_TYPE = "stub.parser"

    def __init__(self, result):
        self._result = result

    def parse(self, _path):
        return self._result


def _result(transactions, iban):
    closing = sum(t.amount_cents for t in transactions)
    return ExtractionResult(
        document_type="stub.parser",
        iban=iban,
        period_start=transactions[0].booking_date,
        period_end=transactions[-1].booking_date,
        opening_balance_cents=0,
        closing_balance_cents=closing,
        transactions=transactions,
    )


@pytest.fixture
def env(monkeypatch):
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        inbox = tmp_path / "inbox"
        archive = tmp_path / "processed"
        inbox.mkdir()
        monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setenv("OTHERMONET_INBOX", str(inbox))
        monkeypatch.setenv("OTHERMONET_ARCHIVE", str(archive))
        db_module.init_db()
        con = db_module.get_db()
        try:
            con.execute("INSERT INTO accounts (iban, owner) VALUES (?, ?)", ["DE_GIRO", "T"])
            con.execute("INSERT INTO accounts (iban, owner) VALUES (?, ?)", ["DE_SPAR", "T"])
        finally:
            con.close()
        yield {"inbox": inbox, "archive": archive}


def test_transfer_leg_classified_as_transfer(env):
    """One leg of an own→own transfer must be marked Kind=Transfer at ingest."""
    txns = [
        ExtractedTransaction(
            booking_date=date(2026, 3, 5),
            value_date=date(2026, 3, 5),
            amount_cents=-50000,
            description="To savings",
            counterparty_iban="DE_SPAR",
            counterparty_name="Self",
        ),
        ExtractedTransaction(
            booking_date=date(2026, 3, 6),
            value_date=date(2026, 3, 6),
            amount_cents=-1250,
            description="EDEKA",
            counterparty_iban="DE_EDEKA",
            counterparty_name="EDEKA",
        ),
    ]
    pdf = env["inbox"] / "giro.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    parser = _StubParser(_result(txns, "DE_GIRO"))
    regs = [
        Registration(
            filename_pattern=re.compile(r"^giro\.pdf$"),
            parser=parser,
            document_type=parser.DOCUMENT_TYPE,
            iban="DE_GIRO",
            account_name="Giro",
            owner_label="T",
            bank_name="B",
        ),
        Registration(
            filename_pattern=re.compile(r"^spar\.pdf$"),
            parser=parser,
            document_type=parser.DOCUMENT_TYPE,
            iban="DE_SPAR",
            account_name="Spar",
            owner_label="T",
            bank_name="B",
        ),
    ]
    ingest_pdf(pdf, regs)

    con = db_module.get_db()
    try:
        rows = con.execute(
            "SELECT description, kind FROM transactions ORDER BY booking_date"
        ).fetchall()
    finally:
        con.close()
    assert ("To savings", "Transfer") in rows
    assert ("EDEKA", "Expense") in rows
