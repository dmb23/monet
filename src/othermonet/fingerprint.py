"""Deterministic transaction fingerprints for dedup (issue 05).

Per the v1 PRD, a Transaction's identity inside one Account is
`(booking_date, amount_cents, normalized_description)`. The unique constraint
on `transactions(account_id, fingerprint)` catches both forms of duplicate
ingest: re-uploaded statements and overlapping period statements.

The normalization rule lives in this module on purpose — Merchant Memory
(issue 09) needs the *counterparty* key, not the description key, so it goes
through `CounterpartyKeyNormalizer` instead.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

_WS_RE = re.compile(r"\s+")
# Bank-printed noise tokens that vary across uploads of the same transaction:
# transaction reference IDs, end-to-end identifiers, mandate references.
# Stripping them lets two overlapping statements collide on fingerprint.
_NOISE_RE = re.compile(
    r"\b(?:end-to-end[- ]?ref(?:erenz)?|mref|cred|ref|tan|svwz)[:\s][^\s]+",
    re.IGNORECASE,
)


def _normalize_description(description: str) -> str:
    """Lowercase, strip bank-printed reference noise, collapse whitespace."""
    s = description.lower()
    s = _NOISE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


class Fingerprinter:
    """Pure-function fingerprint for transactions. No I/O, no DB access."""

    @staticmethod
    def fingerprint(
        account_id: int,
        booking_date: date | str,
        amount_cents: int,
        description: str,
    ) -> str:
        bd = booking_date.isoformat() if isinstance(booking_date, date) else booking_date
        normalized = f"{account_id}:{bd}:{amount_cents}:{_normalize_description(description)}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def compute_file_sha256(path) -> str:
    """SHA-256 of the file at `path`, used for Statement-level dedup."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
