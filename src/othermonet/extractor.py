"""PDFExtractor dispatcher + Reconciliation Gate-driven ingest.

Acceptance criteria (issue 03) are routed through `ingest_pdf`:

- Match Inbox filename against the loaded `Registration` list. No match →
  write `unknown_document_type` sidecar, leave PDF in place.
- Run the registered parser. Any exception → write `parser_error` sidecar.
- Validate via the Reconciliation Gate. Diff > €0.01 → write
  `reconciliation_failed` sidecar AND insert a `statements` row with
  `status = 'needs_review'`. Zero transactions committed.
- Success: insert `statements` row with `status = 'ok'`, insert all
  Transactions in a single DB transaction tied to the statement, then move
  the PDF into the Processed Archive with a `.report.json` sidecar.
"""

from __future__ import annotations

import json
import logging
import shutil
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import archive_dir
from .db import get_db
from .extraction import ExtractionResult
from .reconciliation import Outcome, validate
from .registrations import Registration, match_registration
from .seed import compute_fingerprint

log = logging.getLogger(__name__)


class IngestError(Exception):
    """Raised when a PDF cannot be ingested. The caller-visible sidecar is the contract;
    this exception just unwinds the pipeline."""


def ingest_pdf(pdf_path: Path, registrations: list[Registration]) -> dict[str, Any]:
    """Ingest one PDF. Returns a report dict on success.

    Failures write a sidecar `.error.json` next to the PDF and raise
    `IngestError`. The PDF is only moved on the success path.
    """
    reg = match_registration(pdf_path.name, registrations)
    if reg is None:
        _write_error(
            pdf_path,
            "unknown_document_type",
            {
                "file": pdf_path.name,
                "patterns_tried": [r.filename_pattern.pattern for r in registrations],
            },
        )
        raise IngestError(f"no registration matched {pdf_path.name}")

    try:
        result = reg.parser.parse(pdf_path)
    except Exception as e:
        _write_error(
            pdf_path,
            "parser_error",
            {
                "file": pdf_path.name,
                "parser": reg.document_type,
                "exception_type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            },
        )
        raise IngestError(f"parser raised on {pdf_path.name}") from e

    # Stamp the IBAN from the registration onto the result.
    result = _with_iban(result, reg.iban)

    outcome = validate(result)
    if not outcome.ok:
        _record_needs_review_statement(pdf_path, reg, result)
        _write_error(
            pdf_path,
            "reconciliation_failed",
            {
                "file": pdf_path.name,
                "parser": reg.document_type,
                "expected_closing_cents": outcome.expected_closing_cents,
                "computed_cents": outcome.computed_cents,
                "diff_cents": outcome.diff_cents,
                "diff_eur": outcome.diff_cents / 100,
                "transactions_extracted": outcome.transactions_extracted,
            },
        )
        raise IngestError(
            f"reconciliation failed for {pdf_path.name}: diff_cents={outcome.diff_cents}"
        )

    statement_id = _commit_statement(pdf_path, reg, result)

    dest_dir = archive_dir() / str(result.period_end.year) / reg.owner_label
    dest_dir.mkdir(parents=True, exist_ok=True)
    archived = dest_dir / pdf_path.name
    shutil.move(str(pdf_path), archived)

    report = {
        "file": pdf_path.name,
        "iban": reg.iban,
        "owner": reg.owner_label,
        "document_type": reg.document_type,
        "statement_id": statement_id,
        "transactions_committed": len(result.transactions),
        "archived_to": str(archived),
    }
    archived.with_suffix(archived.suffix + ".report.json").write_text(
        json.dumps(report, indent=2)
    )
    log.info(
        "ingested %s: %d transactions for %s",
        pdf_path.name,
        len(result.transactions),
        reg.owner_label,
    )
    return report


def _with_iban(r: ExtractionResult, iban: str) -> ExtractionResult:
    d = asdict(r)
    d["iban"] = iban
    # `asdict` rebuilds dataclasses → plain dicts; reconstruct manually.
    from .extraction import ExtractedTransaction

    return ExtractionResult(
        document_type=r.document_type,
        iban=iban,
        period_start=r.period_start,
        period_end=r.period_end,
        opening_balance_cents=r.opening_balance_cents,
        closing_balance_cents=r.closing_balance_cents,
        transactions=[
            ExtractedTransaction(**asdict(t)) for t in r.transactions
        ],
    )


def _lookup_account_id(con, iban: str) -> int:
    row = con.execute("SELECT id FROM accounts WHERE iban = ?", [iban]).fetchone()
    if row is None:
        raise IngestError(
            f"account row missing for IBAN {iban}; was reconcile_accounts_table run?"
        )
    return row[0]


def _commit_statement(
    pdf_path: Path, reg: Registration, result: ExtractionResult
) -> int:
    """Insert one statements row and N transactions atomically. Returns statement_id."""
    con = get_db()
    try:
        con.execute("BEGIN")
        account_id = _lookup_account_id(con, reg.iban)
        statement_id = con.execute(
            """INSERT INTO statements
                  (account_id, filename, period_start, period_end,
                   opening_balance, closing_balance, status, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, 'ok', CURRENT_TIMESTAMP)
               RETURNING id""",
            [
                account_id,
                pdf_path.name,
                result.period_start.isoformat(),
                result.period_end.isoformat(),
                result.opening_balance_cents,
                result.closing_balance_cents,
            ],
        ).fetchone()[0]

        for t in result.transactions:
            fingerprint = compute_fingerprint(
                account_id,
                t.booking_date.isoformat(),
                t.amount_cents,
                t.description,
            )
            con.execute(
                """INSERT INTO transactions
                      (statement_id, account_id, fingerprint, booking_date, value_date,
                       amount_cents, description, counterparty_iban, counterparty_name,
                       kind)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    statement_id,
                    account_id,
                    fingerprint,
                    t.booking_date.isoformat(),
                    t.value_date.isoformat() if t.value_date else None,
                    t.amount_cents,
                    t.description,
                    t.counterparty_iban,
                    t.counterparty_name,
                    "Income" if t.amount_cents > 0 else "Expense",
                ],
            )
        con.execute("COMMIT")
        return statement_id
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _record_needs_review_statement(
    pdf_path: Path, reg: Registration, result: ExtractionResult
) -> None:
    """Insert a statements row marked needs_review. No transactions are committed."""
    con = get_db()
    try:
        row = con.execute(
            "SELECT id FROM accounts WHERE iban = ?", [reg.iban]
        ).fetchone()
        if row is None:
            log.warning("no account for IBAN %s; skipping statements row", reg.iban)
            return
        account_id = row[0]
        con.execute(
            """INSERT INTO statements
                  (account_id, filename, period_start, period_end,
                   opening_balance, closing_balance, status, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, 'needs_review', CURRENT_TIMESTAMP)""",
            [
                account_id,
                pdf_path.name,
                result.period_start.isoformat(),
                result.period_end.isoformat(),
                result.opening_balance_cents,
                result.closing_balance_cents,
            ],
        )
    finally:
        con.close()


def _write_error(path: Path, error_type: str, payload: dict[str, Any]) -> None:
    sidecar = path.with_suffix(path.suffix + ".error.json")
    sidecar.write_text(json.dumps({"error_type": error_type, **payload}, indent=2))
