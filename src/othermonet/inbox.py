"""Inbox watcher.

Watches the Inbox directory for newly arrived `.pdf` files and runs each one
through `extractor.ingest_pdf`. Errors land as `.error.json` sidecars next to
the source PDF; the PDF only moves on the success path. See ADR-0001
(reconciliation gate) and ADR-0006 (per-document-type extraction).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import inbox_dir
from .extractor import IngestError, ingest_pdf
from .registrations import Registration

log = logging.getLogger(__name__)


def _is_inbox_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


class InboxHandler(FileSystemEventHandler):
    def __init__(self, registrations: list[Registration]) -> None:
        self._registrations = registrations

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not _is_inbox_pdf(path):
            return
        # Tiny grace window so the writer finishes flushing before we read.
        time.sleep(0.05)
        try:
            ingest_pdf(path, self._registrations)
        except IngestError as e:
            log.warning("ingest failed for %s: %s", path.name, e)
        except Exception:
            log.exception("unexpected error ingesting %s", path.name)


def start_watcher(
    registrations: list[Registration], inbox: Path | None = None
) -> Observer:
    inbox = inbox or inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(InboxHandler(registrations), str(inbox), recursive=False)
    observer.start()
    log.info("inbox watcher started on %s", inbox)
    return observer


def process_existing(
    registrations: list[Registration], inbox: Path | None = None
) -> list[dict]:
    """One-shot sweep of any PDFs already in the inbox at startup."""
    inbox = inbox or inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    for pdf in sorted(inbox.glob("*.pdf")):
        try:
            reports.append(ingest_pdf(pdf, registrations))
        except IngestError as e:
            log.warning("ingest failed for %s: %s", pdf.name, e)
        except Exception:
            log.exception("unexpected error ingesting %s", pdf.name)
    return reports
