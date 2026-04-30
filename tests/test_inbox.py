"""Tests for the Inbox watcher and JSON ingest pipeline."""

import json
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import othermonet.db as db_module
from othermonet.inbox import IngestError, _lookup_account, ingest_file, start_watcher

FIXTURE = Path(__file__).parent / "fixtures" / "extraction_result.json"


@pytest.fixture
def isolated_env(monkeypatch):
    """Point DB, Inbox, and Archive at temp dirs and seed one Account."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        inbox = tmp_path / "inbox"
        archive = tmp_path / "processed"
        inbox.mkdir()

        monkeypatch.setattr(db_module, "DB_PATH", db_path)
        monkeypatch.setenv("OTHERMONET_INBOX", str(inbox))
        monkeypatch.setenv("OTHERMONET_ARCHIVE", str(archive))

        db_module.init_db()
        con = db_module.get_db()
        con.execute(
            "INSERT INTO accounts (iban, owner) VALUES (?, ?)",
            ["DE89370400440532013000", "Mischa"],
        )
        con.close()

        yield {"inbox": inbox, "archive": archive, "db_path": db_path}


def test_lookup_account_returns_id_and_owner(isolated_env):
    con = db_module.get_db()
    try:
        result = _lookup_account(con, "DE89370400440532013000")
    finally:
        con.close()
    assert result is not None
    account_id, owner = result
    assert isinstance(account_id, int)
    assert owner == "Mischa"


def test_lookup_account_unknown_iban_returns_none(isolated_env):
    con = db_module.get_db()
    try:
        assert _lookup_account(con, "DE00000000000000000000") is None
    finally:
        con.close()


def test_ingest_known_iban_commits_and_archives(isolated_env):
    inbox = isolated_env["inbox"]
    archive = isolated_env["archive"]
    src = inbox / "extraction_result.json"
    shutil.copy(FIXTURE, src)

    report = ingest_file(src)

    assert report["transactions_committed"] == 2
    assert report["owner"] == "Mischa"
    assert not src.exists(), "source file should have moved"

    archived = archive / "2024" / "Mischa" / "extraction_result.json"
    assert archived.exists()
    report_sidecar = archived.with_suffix(".json.report.json")
    assert report_sidecar.exists()
    assert json.loads(report_sidecar.read_text())["transactions_committed"] == 2

    con = db_module.get_db()
    try:
        rows = con.execute(
            "SELECT description, amount_cents, kind FROM transactions ORDER BY booking_date"
        ).fetchall()
    finally:
        con.close()
    assert rows == [
        ("ALDI SUED", -1599, "Expense"),
        ("Deutsche Bahn Ticket", -3401, "Expense"),
    ]


def test_ingest_unknown_iban_writes_error_sidecar(isolated_env):
    inbox = isolated_env["inbox"]
    archive = isolated_env["archive"]
    payload = json.loads(FIXTURE.read_text())
    payload["account_iban"] = "DE00000000000000000000"
    src = inbox / "unknown.json"
    src.write_text(json.dumps(payload))

    with pytest.raises(IngestError):
        ingest_file(src)

    assert src.exists(), "source file must remain in inbox"
    error_sidecar = src.with_suffix(".json.error.json")
    assert error_sidecar.exists()
    err = json.loads(error_sidecar.read_text())
    assert err["reason"] == "unknown_iban"
    assert err["iban"] == "DE00000000000000000000"
    assert not archive.exists() or not any(archive.rglob("*.json"))

    con = db_module.get_db()
    try:
        count = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        con.close()
    assert count == 0


def test_watcher_picks_up_new_file(isolated_env):
    inbox = isolated_env["inbox"]
    archive = isolated_env["archive"]
    observer = start_watcher(inbox)
    try:
        dest = inbox / "drop.json"
        shutil.copy(FIXTURE, dest)
        archived = archive / "2024" / "Mischa" / "drop.json"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if archived.exists():
                break
            time.sleep(0.1)
        assert archived.exists(), "watcher did not archive the file within 5s"
    finally:
        observer.stop()
        observer.join()

    con = db_module.get_db()
    try:
        count = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        con.close()
    assert count == 2
