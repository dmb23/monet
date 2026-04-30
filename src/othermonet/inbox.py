"""Inbox ingest pipeline.

Reads `ExtractionResult` JSON files dropped into the Inbox, commits their
Transactions against the matching Account, and moves the file to the
Processed Archive. Unknown IBANs leave the file in the Inbox with a
sidecar `.error.json`.

This slice intentionally skips reconciliation, dedup, Kind classification,
and categorization — those are added in later slices. The Sign rule and
fingerprint are computed as placeholders so the rows satisfy schema
constraints.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import archive_dir, inbox_dir
from .db import get_db
from .seed import compute_fingerprint

log = logging.getLogger(__name__)


class IngestError(Exception):
    """Raised when an ExtractionResult cannot be ingested."""


def _kind_from_amount(amount_cents: int) -> str:
    """Sign-rule placeholder until slice 06 adds full Kind classification."""
    return "Income" if amount_cents > 0 else "Expense"


def _lookup_account(con, iban: str) -> tuple[int, str] | None:
    row = con.execute(
        "SELECT id, owner FROM accounts WHERE iban = ?", [iban]
    ).fetchone()
    return (row[0], row[1]) if row else None


def _archive_destination(archive_root: Path, owner: str, transactions: list[dict]) -> Path:
    """`processed/<year>/<owner>/`, year taken from the first transaction's booking date."""
    year = transactions[0]["booking_date"][:4] if transactions else "unknown"
    return archive_root / year / owner


def _write_error_sidecar(path: Path, reason: str, detail: dict[str, Any]) -> None:
    sidecar = path.with_suffix(path.suffix + ".error.json")
    sidecar.write_text(json.dumps({"reason": reason, **detail}, indent=2))


def ingest_file(path: Path) -> dict[str, Any]:
    """Ingest one ExtractionResult JSON file.

    On success: commits Transactions, moves the file to the archive,
    writes a `.report.json` sidecar next to the archived file, and
    returns the report.

    On unknown IBAN: writes a `.error.json` next to the source file,
    leaves the source in place, and raises `IngestError`.
    """
    payload = json.loads(path.read_text())
    iban = payload["account_iban"]
    transactions = payload.get("transactions", [])

    con = get_db()
    try:
        account = _lookup_account(con, iban)
        if account is None:
            _write_error_sidecar(
                path,
                "unknown_iban",
                {"iban": iban, "file": path.name},
            )
            raise IngestError(f"Unknown IBAN: {iban}")

        account_id, owner = account
        for txn in transactions:
            fingerprint = compute_fingerprint(
                account_id,
                txn["booking_date"],
                txn["amount_cents"],
                txn["description"],
            )
            con.execute(
                """INSERT INTO transactions
                   (account_id, fingerprint, booking_date, value_date, amount_cents,
                    description, counterparty_iban, counterparty_name, kind)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    account_id,
                    fingerprint,
                    txn["booking_date"],
                    txn.get("value_date"),
                    txn["amount_cents"],
                    txn["description"],
                    txn.get("counterparty_iban"),
                    txn.get("counterparty_name"),
                    _kind_from_amount(txn["amount_cents"]),
                ],
            )
    finally:
        con.close()

    dest_dir = _archive_destination(archive_dir(), owner, transactions)
    dest_dir.mkdir(parents=True, exist_ok=True)
    archived = dest_dir / path.name
    shutil.move(str(path), archived)

    report = {
        "file": path.name,
        "account_iban": iban,
        "owner": owner,
        "transactions_committed": len(transactions),
        "archived_to": str(archived),
    }
    archived.with_suffix(archived.suffix + ".report.json").write_text(
        json.dumps(report, indent=2)
    )
    log.info("ingested %s: %d transactions for %s", path.name, len(transactions), owner)
    return report


_SIDECAR_SUFFIXES = (".error.json", ".report.json")


def _is_extraction_result(path: Path) -> bool:
    if path.suffix != ".json":
        return False
    return not any(path.name.endswith(s) for s in _SIDECAR_SUFFIXES)


class InboxHandler(FileSystemEventHandler):
    """Watchdog handler that ingests JSON files dropped into the Inbox."""

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not _is_extraction_result(path):
            return
        # Tiny grace window so the writer finishes flushing before we read.
        time.sleep(0.05)
        try:
            ingest_file(path)
        except IngestError as e:
            log.warning("ingest failed for %s: %s", path.name, e)
        except Exception:
            log.exception("unexpected error ingesting %s", path.name)


def start_watcher(inbox: Path | None = None) -> Observer:
    """Start the Inbox watcher and return the running Observer."""
    inbox = inbox or inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(InboxHandler(), str(inbox), recursive=False)
    observer.start()
    log.info("inbox watcher started on %s", inbox)
    return observer
