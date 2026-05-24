"""Extract Transactions from a Triodos Bank Girokonto Kontoauszug PDF.

The Triodos statement uses fixed column positions on every page, so we drive
camelot in stream-mode with hand-tuned `table_areas` + `columns` rather than
relying on layout heuristics. Page 1 has a different top margin than the rest.

The postprocessor turns the raw cell grid into a `TriodosStatement` with:
- opening / closing `Balance` (signed cents, dated)
- a transactions DataFrame, ready to map onto `transactions` in the schema

Balances and amounts are kept as signed integer cents — Haben (credit) is
positive, Soll (debit) is negative — so reconciliation is a plain integer add.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import camelot
import pandas as pd


_TABLE_AREA_PAGE_1 = "10,550,600,20"
_TABLE_AREA_PAGE_REST = "38,655,587,25"
_COLUMN_BOUNDARIES = "39,74,112,434,526,582"

_AMOUNT_RE = re.compile(r"([\d.]+,\d{2})\s*([SH])")
_KONTOSTAND_RE = re.compile(
    r"(alter|neuer)\s+Kontostand\s+vom\s+(\d{2})\.(\d{2})\.(\d{4})"
)
_UEBERTRAG_RE = re.compile(r"Übertrag\s+(auf|von)\s+Blatt")
_DAY_MONTH_RE = re.compile(r"^(\d{2})\.(\d{2})\.?$")


@dataclass(frozen=True)
class Balance:
    on: date
    amount_cents: int  # signed: positive = Haben, negative = Soll


@dataclass
class TriodosStatement:
    opening: Balance
    closing: Balance
    transactions: pd.DataFrame  # booking_date, value_date, vorgang_type, description, amount_cents

    def reconciles(self) -> bool:
        return (
            self.opening.amount_cents
            + int(self.transactions["amount_cents"].sum())
            == self.closing.amount_cents
        )


def extract_tables(source: Path) -> list[pd.DataFrame]:
    """Run camelot with hand-tuned Triodos column boundaries; one DataFrame per page."""
    source = str(source)
    dfs: list[pd.DataFrame] = [
        camelot.read_pdf(
            source,
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
            source,
            pages="2-end",
            flavor="stream",
            table_areas=[_TABLE_AREA_PAGE_REST],
            columns=[_COLUMN_BOUNDARIES],
            split_text=True,
        )
    )
    return dfs


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


def postprocess_tables(dfs: list[pd.DataFrame]) -> TriodosStatement:
    raw = pd.concat(dfs, ignore_index=True).dropna(axis=1, how="all")
    if raw.shape[1] != 5:
        raise ValueError(
            f"expected 5 non-empty columns after concat, got {raw.shape[1]}"
        )
    raw.columns = ["bu_tag", "wert", "vorgang", "soll", "haben"]
    raw = raw.fillna("")
    for c in raw.columns:
        raw[c] = raw[c].astype(str).str.strip()

    opening: Balance | None = None
    closing: Balance | None = None
    for r in raw.itertuples(index=False):
        m = _KONTOSTAND_RE.search(r.vorgang)
        if m is None:
            continue
        d = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        amt = _parse_amount(r.soll, r.haben)
        if amt is None:
            raise ValueError(f"Kontostand row has no parseable amount: {r}")
        bal = Balance(on=d, amount_cents=amt)
        if m.group(1) == "alter":
            opening = bal
        else:
            closing = bal
    if opening is None or closing is None:
        raise ValueError("statement is missing alter and/or neuer Kontostand row")

    year_hint = closing.on.year
    end_month = closing.on.month

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
            current["description"] = (
                f"{current['description']} {r.vorgang}".strip()
                if current["description"]
                else r.vorgang
            )

    flush()

    transactions = pd.DataFrame(
        rows,
        columns=[
            "booking_date",
            "value_date",
            "vorgang_type",
            "description",
            "amount_cents",
        ],
    )
    return TriodosStatement(opening=opening, closing=closing, transactions=transactions)


def extract_statement(source: Path) -> TriodosStatement:
    return postprocess_tables(extract_tables(source))
