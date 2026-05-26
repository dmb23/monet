"""Integration tests for the PDFExtractor dispatcher across all three failure modes."""

import json
import re
import shutil
import time
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import othermonet.db as db_module
from othermonet.extraction import ExtractedTransaction, ExtractionResult
from othermonet.extractor import IngestError, ingest_pdf
from othermonet.inbox import start_watcher
from othermonet.registrations import Registration
from tests.fixtures import TRIODOS_GIRO_PDF, TRIODOS_KREDITKARTE_PDF

GIRO_PDF = TRIODOS_GIRO_PDF
KK_PDF = TRIODOS_KREDITKARTE_PDF

# Placeholder IBAN used to wire test registrations to test DB rows. The
# Kontoauszug parser does not validate this against the PDF; it is purely a
# lookup key inside the test DuckDB instance.
PLACEHOLDER_GIRO_IBAN = "DE00000000000000000001"


class _StubParser:
    DOCUMENT_TYPE = "stub.parser"

    def __init__(self, behaviour):
        self._behaviour = behaviour

    def parse(self, pdf_path: Path) -> ExtractionResult:
        return self._behaviour(pdf_path)


def _make_registration(parser, pattern: str, iban: str = "DE99STUB") -> Registration:
    return Registration(
        filename_pattern=re.compile(pattern),
        parser=parser,
        document_type=parser.DOCUMENT_TYPE,
        iban=iban,
        account_name="Stub",
        owner_label="Tester",
        bank_name="StubBank",
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
        yield {"inbox": inbox, "archive": archive}


def _insert_account(iban: str, owner: str = "Tester") -> None:
    con = db_module.get_db()
    try:
        con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?)", [iban, owner]
        )
    finally:
        con.close()


def _stub_result(opening=10000, closing=9000, amount=-1000) -> ExtractionResult:
    return ExtractionResult(
        document_type="stub.parser",
        iban="",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        transactions=[
            ExtractedTransaction(
                booking_date=date(2026, 1, 5),
                value_date=date(2026, 1, 5),
                amount_cents=amount,
                description="stub txn",
                counterparty_iban=None,
                counterparty_name=None,
            )
        ],
    )


# ---- failure mode 1: unknown_document_type ----------------------------------


def test_unknown_document_type_sidecar(env):
    pdf = env["inbox"] / "mystery.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")
    parser = _StubParser(lambda p: _stub_result())
    regs = [_make_registration(parser, r"^this-will-not-match\.pdf$")]

    with pytest.raises(IngestError):
        ingest_pdf(pdf, regs)

    assert pdf.exists(), "source PDF must remain in inbox"
    sidecar = pdf.with_suffix(".pdf.error.json")
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text())
    assert payload["error_type"] == "unknown_document_type"
    assert "patterns_tried" in payload
    _assert_no_transactions()


# ---- failure mode 2: parser_error ------------------------------------------


def test_parser_error_sidecar(env):
    pdf = env["inbox"] / "boom.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    _insert_account("DE99STUB")

    def boom(_path):
        raise ValueError("layout shifted: column 4 missing")

    parser = _StubParser(boom)
    regs = [_make_registration(parser, r"^boom\.pdf$")]

    with pytest.raises(IngestError):
        ingest_pdf(pdf, regs)

    assert pdf.exists()
    sidecar = pdf.with_suffix(".pdf.error.json")
    payload = json.loads(sidecar.read_text())
    assert payload["error_type"] == "parser_error"
    assert payload["exception_type"] == "ValueError"
    assert "layout shifted" in payload["message"]
    _assert_no_transactions()


# ---- failure mode 3: reconciliation_failed ---------------------------------


def test_reconciliation_failed_sidecar_and_statements_row(env):
    pdf = env["inbox"] / "bad.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    _insert_account("DE99STUB")
    parser = _StubParser(lambda p: _stub_result(opening=10000, closing=9000, amount=-500))
    regs = [_make_registration(parser, r"^bad\.pdf$")]

    with pytest.raises(IngestError):
        ingest_pdf(pdf, regs)

    sidecar = pdf.with_suffix(".pdf.error.json")
    payload = json.loads(sidecar.read_text())
    assert payload["error_type"] == "reconciliation_failed"
    assert payload["diff_cents"] == 500  # 10000 + (-500) - 9000

    con = db_module.get_db()
    try:
        statements = con.execute(
            "SELECT filename, status FROM statements"
        ).fetchall()
        txn_count = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        con.close()
    assert ("bad.pdf", "needs_review") in statements
    assert txn_count == 0


# ---- happy path on real fixture --------------------------------------------


def test_happy_path_commits_and_archives(env):
    if not GIRO_PDF.exists():
        pytest.skip("real fixture missing")
    src = env["inbox"] / GIRO_PDF.name
    shutil.copy(GIRO_PDF, src)
    _insert_account(PLACEHOLDER_GIRO_IBAN)

    from othermonet import triodos_kontoauszug

    regs = [
        Registration(
            filename_pattern=re.compile(rf"^{re.escape(GIRO_PDF.name)}$"),
            parser=triodos_kontoauszug,
            document_type=triodos_kontoauszug.DOCUMENT_TYPE,
            iban=PLACEHOLDER_GIRO_IBAN,
            account_name="Triodos Girokonto",
            owner_label="Mischa",
            bank_name="Triodos Bank",
        )
    ]
    report = ingest_pdf(src, regs)

    assert report["transactions_committed"] == 25
    assert not src.exists()
    archived = env["archive"] / "2026" / "Mischa" / GIRO_PDF.name
    assert archived.exists()
    assert archived.with_suffix(archived.suffix + ".report.json").exists()

    con = db_module.get_db()
    try:
        n = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        status = con.execute("SELECT status FROM statements").fetchone()[0]
    finally:
        con.close()
    assert n == 25
    assert status == "ok"


def test_watcher_picks_up_pdf(env):
    if not GIRO_PDF.exists():
        pytest.skip("real fixture missing")
    _insert_account(PLACEHOLDER_GIRO_IBAN)

    from othermonet import triodos_kontoauszug

    regs = [
        Registration(
            filename_pattern=re.compile(rf"^{re.escape(GIRO_PDF.name)}$"),
            parser=triodos_kontoauszug,
            document_type=triodos_kontoauszug.DOCUMENT_TYPE,
            iban=PLACEHOLDER_GIRO_IBAN,
            account_name="Triodos Girokonto",
            owner_label="Mischa",
            bank_name="Triodos Bank",
        )
    ]
    observer = start_watcher(regs, env["inbox"])
    try:
        shutil.copy(GIRO_PDF, env["inbox"] / GIRO_PDF.name)
        archived = env["archive"] / "2026" / "Mischa" / GIRO_PDF.name
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not archived.exists():
            time.sleep(0.2)
        assert archived.exists(), "watcher did not archive within 60s"
    finally:
        observer.stop()
        observer.join()


def _assert_no_transactions() -> None:
    con = db_module.get_db()
    try:
        n = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        con.close()
    assert n == 0
