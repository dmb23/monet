# PDF Extraction + Reconciliation Gate

Status: needs-triage
Type: HITL
User stories covered: 2, 5, 6, 7, 8

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Replace the JSON ingest path from slice 02 with a real `PDFExtractor`, built as a **filename-pattern dispatcher** over per-document-type parser modules. Each parser uses `camelot` with hand-tuned layout coordinates to read one PDF format; the dispatcher routes each Inbox file to its registered parser. Every parsed Statement is then run through `ReconciliationValidator` before any of its Transactions are committed.

Per [ADR-0006](../../../docs/adr/0006-pdf-extraction-is-per-document-type.md), extraction is code-driven, not model-driven. Model-based parsers were prototyped in May 2026 and rejected for accuracy reasons.

Per [ADR-0001](../../../docs/adr/0001-reconciliation-gate-is-mandatory-and-binary.md), the Reconciliation Gate is binary: a Statement either reconciles cleanly (`opening_balance + sum(transactions) == closing_balance` within €0.01) and commits all of its Transactions, or it commits **none**. There is no "force commit with warnings" path.

### Three failure modes share one sidecar shape

When ingest does not complete, the PDF stays in the Inbox alongside a sidecar `.error.json` whose `error_type` is one of:

- `unknown_document_type` — no Account Registration filename pattern matched. Payload: the filename and the list of patterns tried.
- `parser_error` — the parser ran but raised. Payload: the parser name, the exception type and message, the page/row index if available.
- `reconciliation_failed` — parser ran cleanly but balances do not match. Payload: `expected_closing`, `computed`, `diff_eur`, `transactions_extracted`.

The dashboard surfaces a banner showing how many Statements (or unmatched PDFs) currently need review, independent of which failure mode produced them.

### Parser modules in this slice

Two parser modules ship as part of this slice:

- **`triodos_kontoauszug`** — Triodos Bank Girokonto/Sparkonto statement. A prototype exists at `src/othermonet/triodos.py`; harden it, add counterparty-IBAN and counterparty-name extraction from the `Vorgang` column, and finalise the `ExtractionResult` shape.
- **`triodos_kreditkarte`** — Triodos Mastercard credit card statement. New module; same `camelot`-with-fixed-coordinates approach as the Kontoauszug parser.

`accounts.toml` (delivered in slice 04) carries three registrations against these two parsers: Triodos Girokonto, Triodos Sparkonto (same parser as Girokonto, different IBAN), and Triodos Mastercard.

### ExtractionResult contract

Every parser returns the same shape:

```
ExtractionResult {
  document_type:           str           # e.g. "triodos.girokonto"
  iban:                    str           # stamped on by the dispatcher from accounts.toml
  period_start:            date
  period_end:              date
  opening_balance_cents:   int           # signed
  closing_balance_cents:   int           # signed
  transactions: [{
    booking_date:          date
    value_date:            date | None
    amount_cents:          int           # signed: positive = credit, negative = debit
    description:           str
    counterparty_iban:     str | None    # extractor populates whenever the PDF carries it
    counterparty_name:     str | None
  }]
}
```

`counterparty_iban` / `counterparty_name` are nullable — cash withdrawals, fees, and interest entries genuinely have no counterparty — but parsers are expected to populate them whenever the bank prints them (SEPA-style Vorgang entries). Missing counterparty data degrades Transfer detection (Kind classification step 2) and Merchant Memory hit rate, so each parser should make a real effort here.

### Why this is HITL

- Per-document-type parser development is iterative: open the PDF, eyeball the layout, tune `table_areas` / `columns`, write the regex for the Vorgang column, run against the fixture, repeat. Cannot be done by an autonomous agent without sample PDFs and human acceptance of the output.
- Edge cases (Übertrag rows, balance straddles, unfamiliar Vorgangstypen) only surface against real bank PDFs and require human judgement on each fix.
- The `accounts.toml` registrations bake in real IBANs and account names — needs the user to provide them.

## Acceptance criteria

- [ ] `PDFExtractor` dispatcher matches Inbox filenames against Account Registrations and routes to the registered parser; falsy match yields `unknown_document_type` sidecar
- [ ] `triodos_kontoauszug` parser produces a correct `ExtractionResult` for the Triodos Girokonto and Sparkonto sample PDFs in `data/`, including populated `counterparty_iban` / `counterparty_name` for SEPA-style entries
- [ ] `triodos_kreditkarte` parser produces a correct `ExtractionResult` for the Triodos Mastercard sample PDF in `data/`
- [ ] `ReconciliationValidator.validate(ExtractionResult) → Outcome` enforces `opening + sum == closing` within €0.01
- [ ] Failing Statements (any of the three failure modes): PDF stays in Inbox; sidecar `.error.json` with `error_type` is written; zero Transactions are committed; if the parser ran, a `statements` row is written with `status = needs_review`
- [ ] Successful Statements: all Transactions committed in a single DB transaction; PDF moves to Processed Archive
- [ ] Dashboard shows a banner: "N statements need review" covering all three failure modes
- [ ] Golden-file tests for each parser module: real PDF fixture + expected `ExtractionResult` pinned in the repo
- [ ] Table-driven tests for `ReconciliationValidator` covering: balanced, off-by-€0.01, off-by-cents, sign-flipped row, missing row
- [ ] Integration test for each failure mode: drop a doctored input (unmatched filename / parser-raising PDF / non-reconciling fixture), assert the correct `error_type` sidecar appears and zero Transactions are committed
- [ ] README setup section explains how to add a new document type (new parser module + new registration) — pointing at the `triodos_kontoauszug` parser as the worked example

## Blocked by

- Slice 02 (Folder Watcher + JSON Ingest)
- Slice 04 (Account Registration via Config) — needed for the `accounts.toml`-driven IBAN binding

## Note

The Triodos prototype at `src/othermonet/triodos.py` is the starting point for the `triodos_kontoauszug` parser. Notable gaps to close as part of this slice: it does not yet extract counterparty IBAN / name, does not stamp `document_type`, and uses `pd.DataFrame` internally — the boundary should convert to the typed `ExtractionResult` shape above.
