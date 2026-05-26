"""Table-driven tests for Fingerprinter and CounterpartyKeyNormalizer (issue 05)."""

from __future__ import annotations

from datetime import date

import pytest

from othermonet.counterparty import CounterpartyKeyNormalizer
from othermonet.fingerprint import Fingerprinter


# ----- Fingerprinter ---------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        # Identical: same fingerprint.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn"),
            (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn"),
        ),
        # Case differences ignored.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn"),
            (1, date(2026, 1, 15), -1250, "edeka nordhorn"),
        ),
        # Whitespace differences ignored.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA  Nordhorn"),
            (1, date(2026, 1, 15), -1250, "  EDEKA Nordhorn  "),
        ),
        # date object vs ISO string equivalence.
        (
            (1, date(2026, 1, 15), -1250, "x"),
            (1, "2026-01-15", -1250, "x"),
        ),
        # Bank reference noise stripped — two prints of same transaction collide.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn SVWZ:ref123 MREF:abc"),
            (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn"),
        ),
    ],
)
def test_fingerprint_collisions(a, b):
    assert Fingerprinter.fingerprint(*a) == Fingerprinter.fingerprint(*b)


@pytest.mark.parametrize(
    "a, b",
    [
        # Different amount → distinct.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA"),
            (1, date(2026, 1, 15), -1251, "EDEKA"),
        ),
        # Different date → distinct.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA"),
            (1, date(2026, 1, 16), -1250, "EDEKA"),
        ),
        # Different account → distinct (same booking elsewhere is a different tx).
        (
            (1, date(2026, 1, 15), -1250, "EDEKA"),
            (2, date(2026, 1, 15), -1250, "EDEKA"),
        ),
        # Different merchant → distinct.
        (
            (1, date(2026, 1, 15), -1250, "EDEKA"),
            (1, date(2026, 1, 15), -1250, "REWE"),
        ),
    ],
)
def test_fingerprint_distinct(a, b):
    assert Fingerprinter.fingerprint(*a) != Fingerprinter.fingerprint(*b)


def test_fingerprint_is_pure():
    # Same inputs → same output across many calls.
    args = (1, date(2026, 1, 15), -1250, "EDEKA Nordhorn")
    fps = {Fingerprinter.fingerprint(*args) for _ in range(50)}
    assert len(fps) == 1


# ----- CounterpartyKeyNormalizer --------------------------------------------


@pytest.mark.parametrize(
    "iban, name, expected",
    [
        # IBAN present → IBAN wins.
        ("DE89370400440532013000", "anything", "DE89370400440532013000"),
        # IBAN case + whitespace normalised.
        ("  de89 3704 0044 0532 0130 00 ", "x", "DE89370400440532013000"),
        # IBAN-absent → name normalisation.
        (None, "EDEKA Nordhorn", "edeka nordhorn"),
        ("", "EDEKA Nordhorn", "edeka nordhorn"),
        # Legal-form suffix stripped.
        (None, "Acme GmbH", "acme"),
        (None, "Acme AG", "acme"),
        (None, "Acme SE", "acme"),
        (None, "Acme GmbH & Co. KG", "acme"),
        (None, "Beispiel e.K.", "beispiel"),
        # Casing + whitespace.
        (None, "  REWE  City  ", "rewe city"),
        # Punctuation collapsed.
        (None, "Café, Bar & Grill.", "café bar & grill"),
    ],
)
def test_counterparty_key(iban, name, expected):
    assert CounterpartyKeyNormalizer.key(iban, name) == expected


def test_counterparty_key_is_pure():
    args = (None, "Acme GmbH")
    keys = {CounterpartyKeyNormalizer.key(*args) for _ in range(50)}
    assert len(keys) == 1
