"""Integration tests for dedup (issue 05): file-level and fingerprint-level."""

from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import othermonet.db as db_module
from othermonet.extraction import ExtractedTransaction, ExtractionResult
from othermonet.extractor import ingest_pdf
from othermonet.registrations import Registration


class _StubParser:
    """Returns a pre-canned ExtractionResult regardless of the PDF bytes."""

    DOCUMENT_TYPE = "stub.parser"

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    def parse(self, pdf_path: Path) -> ExtractionResult:
        return self._result


def _registration(parser, pattern: str, iban: str = "DE99STUB") -> Registration:
    return Registration(
        filename_pattern=re.compile(pattern),
        parser=parser,
        document_type=parser.DOCUMENT_TYPE,
        iban=iban,
        account_name="Stub",
        owner_label="Tester",
        bank_name="StubBank",
    )


def _txn(d: date, amount: int, desc: str) -> ExtractedTransaction:
    return ExtractedTransaction(
        booking_date=d,
        value_date=d,
        amount_cents=amount,
        description=desc,
        counterparty_iban=None,
        counterparty_name=None,
    )


def _result(transactions, opening=0):
    closing = opening + sum(t.amount_cents for t in transactions)
    return ExtractionResult(
        document_type="stub.parser",
        iban="",
        period_start=transactions[0].booking_date,
        period_end=transactions[-1].booking_date,
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        transactions=transactions,
    )


def _insert_account(iban: str) -> None:
    con = db_module.get_db()
    try:
        con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?)", [iban, "Tester"]
        )
    finally:
        con.close()


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
        _insert_account("DE99STUB")
        yield {"inbox": inbox, "archive": archive, "tmp": tmp_path}


def _txn_count() -> int:
    con = db_module.get_db()
    try:
        return con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        con.close()


def test_overlapping_statements_dedup(env):
    """March-only and Q1 statements: March transactions land exactly once."""
    march_txns = [
        _txn(date(2026, 3, 5), -1000, "EDEKA"),
        _txn(date(2026, 3, 12), -2000, "REWE"),
    ]
    q1_txns = [
        _txn(date(2026, 1, 10), -500, "Coffee"),
        _txn(date(2026, 2, 8), -800, "Lunch"),
        _txn(date(2026, 3, 5), -1000, "EDEKA"),  # duplicate of march_txns[0]
        _txn(date(2026, 3, 12), -2000, "REWE"),  # duplicate of march_txns[1]
    ]

    march_pdf = env["inbox"] / "march.pdf"
    march_pdf.write_bytes(b"%PDF-1.4 march-only")
    march_parser = _StubParser(_result(march_txns))
    regs_march = [_registration(march_parser, r"^march\.pdf$")]
    report = ingest_pdf(march_pdf, regs_march)
    assert report["transactions_imported"] == 2
    assert report["duplicates_skipped"] == 0
    assert _txn_count() == 2

    q1_pdf = env["inbox"] / "q1.pdf"
    q1_pdf.write_bytes(b"%PDF-1.4 q1-different-bytes")
    q1_parser = _StubParser(_result(q1_txns))
    regs_q1 = [_registration(q1_parser, r"^q1\.pdf$")]
    report = ingest_pdf(q1_pdf, regs_q1)
    assert report["transactions_imported"] == 2
    assert report["duplicates_skipped"] == 2
    assert report["summary"] == "2 imported, 2 duplicates skipped"
    assert _txn_count() == 4


def test_file_level_dedup_on_reupload(env):
    """Re-uploading the exact same bytes: skipped before parser even runs."""
    txns = [_txn(date(2026, 3, 5), -1000, "EDEKA")]

    pdf_bytes = b"%PDF-1.4 deterministic-content"
    first = env["inbox"] / "stmt.pdf"
    first.write_bytes(pdf_bytes)
    parser = _StubParser(_result(txns))
    regs = [_registration(parser, r"^stmt\.pdf$")]
    report = ingest_pdf(first, regs)
    assert report["transactions_imported"] == 1
    assert _txn_count() == 1

    # Now drop the same bytes again under a different filename. The dispatcher
    # must short-circuit on the SHA-256 match, without re-parsing.
    class _ExplodingParser:
        DOCUMENT_TYPE = "stub.parser"

        def parse(self, _path):
            raise AssertionError("parser must not run on a duplicate file")

    second = env["inbox"] / "stmt-copy.pdf"
    second.write_bytes(pdf_bytes)
    regs_dup = [_registration(_ExplodingParser(), r"^stmt-copy\.pdf$")]
    report = ingest_pdf(second, regs_dup)
    assert report["status"] == "duplicate_statement"
    assert report["matched_filename"] == "stmt.pdf"
    assert not second.exists(), "duplicate file should move to archive"
    assert _txn_count() == 1


def test_report_summary_format(env):
    """The report carries an explicit 'N imported, M duplicates skipped' string."""
    txns = [
        _txn(date(2026, 3, 5), -1000, "A"),
        _txn(date(2026, 3, 6), -2000, "B"),
        _txn(date(2026, 3, 7), -3000, "C"),
    ]
    pdf = env["inbox"] / "first.pdf"
    pdf.write_bytes(b"%PDF-1.4 a")
    regs = [_registration(_StubParser(_result(txns)), r"^first\.pdf$")]
    report = ingest_pdf(pdf, regs)
    assert report["summary"] == "3 imported, 0 duplicates skipped"

    # All three reappear in a second statement → 0 imported, 3 skipped.
    pdf2 = env["inbox"] / "second.pdf"
    pdf2.write_bytes(b"%PDF-1.4 b-different-bytes")
    regs2 = [_registration(_StubParser(_result(txns)), r"^second\.pdf$")]
    report2 = ingest_pdf(pdf2, regs2)
    assert report2["summary"] == "0 imported, 3 duplicates skipped"
