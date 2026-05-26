"""Parser for Triodos Bank Girokonto/Sparkonto Kontoauszug PDFs.

The Triodos statement uses fixed column positions on every page, so we drive
camelot in stream-mode with hand-tuned `table_areas` + `columns`. Page 1 has
a different top margin than the rest.

This is one parser module conforming to the contract in `extraction.py`.
Multiple Account Registrations can point at this parser (Girokonto + Sparkonto
share the layout); IBAN binding lives in `accounts.toml`, not here.

Amounts are signed integer cents: Haben (credit) is positive, Soll (debit)
is negative — so reconciliation is a plain integer add.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import camelot
import pandas as pd

from .extraction import ExtractedTransaction, ExtractionResult

DOCUMENT_TYPE = "triodos.girokonto"

_TABLE_AREA_PAGE_1 = "10,550,600,20"
_TABLE_AREA_PAGE_REST = "38,655,587,25"
_COLUMN_BOUNDARIES = "39,74,112,434,526,582"

_AMOUNT_RE = re.compile(r"([\d.]+,\d{2})\s*([SH])")
_KONTOSTAND_RE = re.compile(
    r"(alter|neuer)\s+Kontostand\s+vom\s+(\d{2})\.(\d{2})\.(\d{4})"
)
_UEBERTRAG_RE = re.compile(r"Übertrag\s+(auf|von)\s+Blatt|^\s*Vorgang\s*$")
_DAY_MONTH_RE = re.compile(r"^(\d{2})\.(\d{2})\.?$")
_IBAN_RE = re.compile(r"IBAN:\s*([A-Z]{2}\d{2}[A-Z0-9 ]+)")
_IBAN_STOP_RE = re.compile(r"\s+(BIC|CRED|EREF|MREF|ABWA|ANAM|SVWZ|/\*)\b")
_SEPA_MARKERS_RE = re.compile(
    r"\s+(EREF|MREF|CRED|ABWA|ANAM|SVWZ|IBAN|BIC|/\*DA-)\b"
)


def parse(pdf_path: Path) -> ExtractionResult:
    raw = _extract_raw(pdf_path)
    return _postprocess(raw)


def _extract_raw(source: Path) -> pd.DataFrame:
    """Run camelot with hand-tuned coordinates; return one merged DataFrame."""
    src = str(source)
    dfs: list[pd.DataFrame] = [
        camelot.read_pdf(
            src,
            pages="1",
            flavor="stream",
            table_areas=[_TABLE_AREA_PAGE_1],
            columns=[_COLUMN_BOUNDARIES],
            split_text=True,
        )[0].df
    ]
    dfs.extend(
        t.df
        for t in camelot.read_pdf(
            src,
            pages="2-end",
            flavor="stream",
            table_areas=[_TABLE_AREA_PAGE_REST],
            columns=[_COLUMN_BOUNDARIES],
            split_text=True,
        )
    )
    raw = pd.concat(dfs, ignore_index=True)
    # Newer camelot may emit two extra always-empty edge columns; trim if so.
    if raw.shape[1] == 7:
        raw = raw.iloc[:, 1:6]
    if raw.shape[1] != 5:
        raise ValueError(
            f"expected 5 content columns from Triodos Kontoauszug, got {raw.shape[1]}"
        )
    raw.columns = ["bu_tag", "wert", "vorgang", "soll", "haben"]
    raw = raw.fillna("")
    for c in raw.columns:
        raw[c] = raw[c].astype(str).str.strip()
    return raw


def _to_cents(amount_str: str) -> int:
    return int(amount_str.replace(".", "").replace(",", ""))


def _parse_amount(*cells: str) -> int | None:
    """Pull a signed cents amount out of one or more concatenated cells.

    Wide amounts like `10.000,00 H` occasionally straddle the Soll/Haben
    boundary; joining without a separator before searching handles both the
    straddled case and the normal single-cell case.
    """
    joined = "".join(c for c in cells if c)
    m = _AMOUNT_RE.search(joined)
    if m is None:
        return None
    sign = 1 if m.group(2) == "H" else -1
    return sign * _to_cents(m.group(1))


def _parse_day_month(s: str, year_hint: int, end_month: int) -> date | None:
    m = _DAY_MONTH_RE.match(s)
    if m is None:
        return None
    day = int(m.group(1))
    month = int(m.group(2))
    year = year_hint - 1 if month > end_month else year_hint
    return date(year, month, day)


def _extract_counterparty(description: str) -> tuple[str | None, str | None]:
    """Return (counterparty_iban, counterparty_name) from a joined description.

    Counterparty IBAN: the IBAN printed under `IBAN:` in SEPA-style entries.
    Counterparty name: the leading text before any SEPA marker (EREF/MREF/…)
    or standing-order tag (/*DA-…).
    """
    iban_match = _IBAN_RE.search(description)
    iban: str | None = None
    if iban_match:
        raw_iban = iban_match.group(1)
        stop = _IBAN_STOP_RE.search(raw_iban)
        if stop:
            raw_iban = raw_iban[: stop.start()]
        iban = re.sub(r"\s+", "", raw_iban)[:34] or None

    marker = _SEPA_MARKERS_RE.search(description)
    name = description[: marker.start()].strip() if marker else description.strip()
    # Trim trailing reference numbers / noise after the human-readable bit.
    name = re.sub(r"\s{2,}", " ", name)
    return iban, (name or None)


def _postprocess(raw: pd.DataFrame) -> ExtractionResult:
    opening: tuple[date, int] | None = None
    closing: tuple[date, int] | None = None
    for r in raw.itertuples(index=False):
        m = _KONTOSTAND_RE.search(r.vorgang)
        if m is None:
            continue
        d = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        amt = _parse_amount(r.soll, r.haben)
        if amt is None:
            raise ValueError(f"Kontostand row has no parseable amount: {r}")
        if m.group(1) == "alter":
            opening = (d, amt)
        else:
            closing = (d, amt)
    if opening is None or closing is None:
        raise ValueError("statement is missing alter and/or neuer Kontostand row")

    year_hint = closing[0].year
    end_month = closing[0].month

    rows: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current["description"] = current["description"].strip()
            rows.append(current)
            current = None

    for r in raw.itertuples(index=False):
        if _KONTOSTAND_RE.search(r.vorgang) or _UEBERTRAG_RE.search(r.vorgang):
            flush()
            continue

        booking = _parse_day_month(r.bu_tag, year_hint, end_month)
        if booking is not None:
            flush()
            amt = _parse_amount(r.soll, r.haben)
            if amt is None:
                raise ValueError(f"transaction row has no parseable amount: {r}")
            current = {
                "booking_date": booking,
                "value_date": _parse_day_month(r.wert, year_hint, end_month),
                "vorgang_type": r.vorgang,
                "description": "",
                "amount_cents": amt,
            }
        elif current is not None and r.vorgang:
            # Defensive: in case page-break text bleeds into a continuation row.
            if _UEBERTRAG_RE.search(r.vorgang):
                continue
            current["description"] = (
                f"{current['description']} {r.vorgang}".strip()
                if current["description"]
                else r.vorgang
            )

    flush()

    transactions: list[ExtractedTransaction] = []
    for row in rows:
        full_desc = (
            f"{row['vorgang_type']} {row['description']}".strip()
            if row["vorgang_type"]
            else row["description"]
        )
        cp_iban, cp_name = _extract_counterparty(row["description"])
        transactions.append(
            ExtractedTransaction(
                booking_date=row["booking_date"],
                value_date=row["value_date"],
                amount_cents=row["amount_cents"],
                description=full_desc,
                counterparty_iban=cp_iban,
                counterparty_name=cp_name,
            )
        )

    return ExtractionResult(
        document_type=DOCUMENT_TYPE,
        iban="",  # stamped on by the dispatcher from the registration
        period_start=opening[0],
        period_end=closing[0],
        opening_balance_cents=opening[1],
        closing_balance_cents=closing[1],
        transactions=transactions,
    )
