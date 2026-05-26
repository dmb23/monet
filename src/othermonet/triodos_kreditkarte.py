"""Parser for Triodos Bank Mastercard Kreditkarten-Umsatzaufstellung PDFs.

Layout fits a 6-column stream extraction without hand-tuned coordinates:
`buchungs-datum | beleg-datum | umsatzinformationen | währungsbetrag | kurs | betrag (EUR)`.

The credit-card statement is a closed system: opening balance is `Saldo Vormonat`,
closing balance is `Saldo` on the last page. Amounts carry a trailing `+` (credit)
or `-` (debit). The page-break `Zwischensaldo` / `Übertrag` rows are ignored; the
`Auslandseinsatzentgelt` continuation rows are committed as their own debit
transactions (they are real fees on the statement).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import camelot
import pandas as pd
import pypdf

from .extraction import ExtractedTransaction, ExtractionResult

DOCUMENT_TYPE = "triodos.kreditkarte"

_AMOUNT_RE = re.compile(r"([\d.]+,\d{2})([+\-])")
_DAY_MONTH_RE = re.compile(r"^(\d{2})\.(\d{2})\.?$")
_PERIOD_RE = re.compile(
    r"vom\s+(\d{2})\.(\d{2})\.(\d{4})\s+bis\s+(\d{2})\.(\d{2})\.(\d{4})"
)
_SALDO_VORMONAT_RE = re.compile(r"Saldo\s+Vormonat", re.IGNORECASE)
_SALDO_FINAL_RE = re.compile(r"^\s*Saldo\s*$", re.IGNORECASE)
_ZWISCHEN_RE = re.compile(r"Zwischensaldo|Übertrag", re.IGNORECASE)
_FEE_RE = re.compile(r"Auslandseinsatzentgelt", re.IGNORECASE)


def parse(pdf_path: Path) -> ExtractionResult:
    src = str(pdf_path)
    tables = camelot.read_pdf(src, pages="all", flavor="stream", split_text=True)
    period_start, period_end = _extract_period(tables)
    rows = _collect_rows(tables)
    opening = _find_balance(rows, _SALDO_VORMONAT_RE)
    closing = _find_balance(rows, _SALDO_FINAL_RE)
    if opening is None or closing is None:
        opening_txt, closing_txt = _balances_from_text(pdf_path)
        opening = opening if opening is not None else opening_txt
        closing = closing if closing is not None else closing_txt
    if opening is None:
        raise ValueError("kreditkarte statement is missing 'Saldo Vormonat' row")
    if closing is None:
        raise ValueError("kreditkarte statement is missing closing 'Saldo' row")

    transactions = _build_transactions(rows, period_end)

    return ExtractionResult(
        document_type=DOCUMENT_TYPE,
        iban="",  # stamped on by the dispatcher
        period_start=period_start,
        period_end=period_end,
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        transactions=transactions,
    )


def _to_cents(amount_str: str) -> int:
    return int(amount_str.replace(".", "").replace(",", ""))


def _parse_amount(text: str) -> int | None:
    m = _AMOUNT_RE.search(text)
    if m is None:
        return None
    sign = 1 if m.group(2) == "+" else -1
    return sign * _to_cents(m.group(1))


def _parse_day_month(s: str, year_hint: int, end_month: int) -> date | None:
    m = _DAY_MONTH_RE.match(s.strip())
    if m is None:
        return None
    day = int(m.group(1))
    month = int(m.group(2))
    year = year_hint - 1 if month > end_month else year_hint
    return date(year, month, day)


def _extract_period(tables) -> tuple[date, date]:
    for t in tables:
        for joined in t.df.astype(str).agg(" ".join, axis=1):
            m = _PERIOD_RE.search(joined)
            if m:
                start = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                end = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
                return start, end
    raise ValueError("kreditkarte statement missing 'vom … bis …' period header")


def _normalize_row(row: pd.Series) -> list[str]:
    return [str(c).strip() for c in row.tolist()]


def _collect_rows(tables) -> list[list[str]]:
    """Concat the data tables (skipping the address-block tables) into one row list."""
    out: list[list[str]] = []
    for t in tables:
        if t.df.shape[1] < 6:
            continue
        df = t.df.iloc[:, :6]
        for _, r in df.iterrows():
            out.append(_normalize_row(r))
    return out


def _find_balance(rows: list[list[str]], marker_re: re.Pattern[str]) -> int | None:
    """Return the signed cents value on a row whose description matches `marker_re`."""
    for cells in rows:
        descr = cells[2]
        if marker_re.search(descr):
            amt = _parse_amount(cells[-1])
            if amt is not None:
                return amt
            # Some final-Saldo rows place the amount in a different cell — scan all.
            for c in cells:
                amt = _parse_amount(c)
                if amt is not None:
                    return amt
    return None


def _build_transactions(
    rows: list[list[str]], period_end: date
) -> list[ExtractedTransaction]:
    year_hint = period_end.year
    end_month = period_end.month
    txns: list[ExtractedTransaction] = []
    current: ExtractedTransaction | None = None
    for cells in rows:
        bu, beleg, descr, _waehrung, _kurs, betrag = cells
        if _SALDO_VORMONAT_RE.search(descr) or _SALDO_FINAL_RE.search(descr):
            current = None
            continue
        if _ZWISCHEN_RE.search(descr):
            current = None
            continue

        booking = _parse_day_month(bu, year_hint, end_month)
        if booking is not None:
            amt = _parse_amount(betrag)
            if amt is None:
                continue
            value_date = _parse_day_month(beleg, year_hint, end_month)
            name = _clean_merchant(descr)
            current = ExtractedTransaction(
                booking_date=booking,
                value_date=value_date,
                amount_cents=amt,
                description=descr.replace("\n", " ").strip(),
                counterparty_iban=None,
                counterparty_name=name,
            )
            txns.append(current)
            continue

        # Continuation row without a booking date: handle the Auslandseinsatzentgelt
        # fee line that follows a foreign-currency purchase.
        if _FEE_RE.search(descr):
            amt = _parse_amount(betrag)
            if amt is not None and current is not None:
                txns.append(
                    ExtractedTransaction(
                        booking_date=current.booking_date,
                        value_date=current.value_date,
                        amount_cents=amt,
                        description=descr.replace("\n", " ").strip(),
                        counterparty_iban=None,
                        counterparty_name="Auslandseinsatzentgelt",
                    )
                )
    return txns


_SALDO_VORMONAT_LINE_RE = re.compile(
    r"Saldo\s+Vormonat\s+([\d.]+,\d{2})([+\-])", re.IGNORECASE
)
_SALDO_FINAL_LINE_RE = re.compile(
    r"(?:^|\s)Saldo\s+([\d.]+,\d{2})([+\-])\s*$", re.IGNORECASE | re.MULTILINE
)


def _balances_from_text(pdf_path: Path) -> tuple[int | None, int | None]:
    """Fallback: pull opening + closing from raw page text when camelot misses them."""
    opening: int | None = None
    closing: int | None = None
    reader = pypdf.PdfReader(str(pdf_path))
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            if opening is None:
                m = _SALDO_VORMONAT_LINE_RE.search(line)
                if m:
                    sign = 1 if m.group(2) == "+" else -1
                    opening = sign * _to_cents(m.group(1))
                    continue
            m = _SALDO_FINAL_LINE_RE.search(line.strip())
            if m and not _SALDO_VORMONAT_LINE_RE.search(line):
                sign = 1 if m.group(2) == "+" else -1
                closing = sign * _to_cents(m.group(1))
    return opening, closing


def _clean_merchant(descr: str) -> str | None:
    """The first line of the Umsatzinformationen cell is the merchant name."""
    first = descr.split("\n", 1)[0].strip()
    return first or None
