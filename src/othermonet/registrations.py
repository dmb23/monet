"""Account Registration loader.

Reads `accounts.toml`, validates each entry, and reconciles the `accounts`
table at startup. Each registration binds a filename pattern + parser + IBAN
+ account metadata. See ADR-0006 for why this replaces the "register on first
unknown IBAN" UX from the original PRD.
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import triodos_kontoauszug, triodos_kreditkarte
from .db import get_db

log = logging.getLogger(__name__)


_PARSERS = {
    triodos_kontoauszug.DOCUMENT_TYPE: triodos_kontoauszug,
    triodos_kreditkarte.DOCUMENT_TYPE: triodos_kreditkarte,
}


@dataclass(frozen=True)
class Registration:
    filename_pattern: re.Pattern[str]
    parser: object  # parser module
    document_type: str
    iban: str
    account_name: str
    owner_label: str
    bank_name: str


class RegistrationError(Exception):
    """Raised when accounts.toml is malformed."""


def _accounts_toml_path() -> Path:
    return Path(os.environ.get("OTHERMONET_ACCOUNTS_TOML", "accounts.toml"))


_REQUIRED_FIELDS = (
    "filename_pattern",
    "parser",
    "iban",
    "account_name",
    "owner_label",
    "bank_name",
)


def load_registrations(path: Path | None = None) -> list[Registration]:
    """Parse and validate accounts.toml. Returns one Registration per entry.

    Raises RegistrationError with a precise message on:
    - missing or unreadable file
    - TOML parse error
    - missing required field
    - duplicate IBAN
    - unknown parser name
    - invalid filename regex
    """
    path = path or _accounts_toml_path()
    if not path.exists():
        raise RegistrationError(f"accounts.toml not found at {path}")

    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise RegistrationError(f"accounts.toml is not valid TOML: {e}") from e

    entries = data.get("account", [])
    if not entries:
        raise RegistrationError("accounts.toml has no [[account]] entries")

    seen_ibans: set[str] = set()
    registrations: list[Registration] = []
    for i, entry in enumerate(entries):
        missing = [f for f in _REQUIRED_FIELDS if f not in entry]
        if missing:
            raise RegistrationError(
                f"[[account]] entry #{i} is missing fields: {', '.join(missing)}"
            )

        parser_name = entry["parser"]
        if parser_name not in _PARSERS:
            raise RegistrationError(
                f"[[account]] entry #{i} references unknown parser {parser_name!r}; "
                f"known: {sorted(_PARSERS)}"
            )
        parser = _PARSERS[parser_name]

        iban = entry["iban"]
        if iban in seen_ibans:
            raise RegistrationError(f"duplicate IBAN in accounts.toml: {iban}")
        seen_ibans.add(iban)

        try:
            pattern = re.compile(entry["filename_pattern"])
        except re.error as e:
            raise RegistrationError(
                f"[[account]] entry #{i} has invalid filename_pattern regex: {e}"
            ) from e

        registrations.append(
            Registration(
                filename_pattern=pattern,
                parser=parser,
                document_type=parser.DOCUMENT_TYPE,
                iban=iban,
                account_name=entry["account_name"],
                owner_label=entry["owner_label"],
                bank_name=entry["bank_name"],
            )
        )

    return registrations


def reconcile_accounts_table(registrations: list[Registration]) -> None:
    """Idempotent sync of accounts table against registrations.

    - Unknown IBAN → INSERT new row.
    - Existing IBAN with changed metadata → UPDATE in place.
    - IBAN no longer in registrations → leave existing row alone (no silent delete).
    """
    con = get_db()
    try:
        for r in registrations:
            existing = con.execute(
                "SELECT owner, account_name, bank_name FROM accounts WHERE iban = ?",
                [r.iban],
            ).fetchone()
            if existing is None:
                con.execute(
                    """INSERT INTO accounts (iban, owner, account_name, bank_name)
                       VALUES (?, ?, ?, ?)""",
                    [r.iban, r.owner_label, r.account_name, r.bank_name],
                )
                log.info("registered new account: %s (%s)", r.account_name, r.iban)
            elif existing != (r.owner_label, r.account_name, r.bank_name):
                con.execute(
                    """UPDATE accounts
                          SET owner = ?, account_name = ?, bank_name = ?
                        WHERE iban = ?""",
                    [r.owner_label, r.account_name, r.bank_name, r.iban],
                )
                log.info("updated account metadata: %s (%s)", r.account_name, r.iban)
    finally:
        con.close()


def match_registration(
    filename: str, registrations: list[Registration]
) -> Registration | None:
    """Return the first registration whose filename_pattern matches, or None."""
    for r in registrations:
        if r.filename_pattern.search(filename):
            return r
    return None
