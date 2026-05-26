"""Counterparty key normalization (issue 05).

Used by Fingerprinter only indirectly (description is the dedup key), but the
normalized counterparty key is the primary lookup for Merchant Memory
(issue 09). Keeping the rule in its own module avoids divergence between
ingest and Merchant Memory.

Rule, in order of priority:
1. If IBAN is present and non-empty, the key IS the IBAN (uppercased, no
   internal whitespace). IBANs are globally unique enough that nothing else
   matters.
2. Otherwise, normalize the printed name: lowercase, strip German legal-form
   suffixes (GmbH, AG, SE, KG, e.K., UG, mbH, & Co.), strip leading/trailing
   punctuation, collapse internal whitespace.
"""

from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s&]")
# Order matters: longer forms first so "GmbH & Co. KG" collapses cleanly.
_LEGAL_SUFFIXES = (
    "gmbh & co. kg",
    "gmbh & co kg",
    "gmbh & co.",
    "gmbh & co",
    "e.k.",
    "e. k.",
    "mbh",
    "gmbh",
    "ag",
    "se",
    "kg",
    "ug",
    "ohg",
    "ev",
    "e.v.",
)


class CounterpartyKeyNormalizer:
    """Pure-function counterparty key. No I/O, no DB access."""

    @staticmethod
    def key(iban: str | None, name: str) -> str:
        if iban and iban.strip():
            return _WS_RE.sub("", iban).upper()

        s = (name or "").lower()
        s = _WS_RE.sub(" ", s).strip()
        # Repeatedly strip trailing legal suffixes (handles "x GmbH & Co. KG").
        changed = True
        while changed:
            changed = False
            for suffix in _LEGAL_SUFFIXES:
                if s.endswith(" " + suffix) or s == suffix:
                    s = s[: -len(suffix)].rstrip(" ,.")
                    changed = True
                    break
        s = _PUNCT_RE.sub(" ", s)
        s = _WS_RE.sub(" ", s).strip()
        return s
