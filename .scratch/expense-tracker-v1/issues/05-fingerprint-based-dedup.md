# Fingerprint-Based Dedup

Status: needs-triage
Type: AFK
User stories covered: 10, 11

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Add `Fingerprinter` and `CounterpartyKeyNormalizer` modules. At ingest, every Transaction is assigned a deterministic Fingerprint computed as `hash(account_id, booking_date, amount_cents, normalized_description)`. The `transactions.fingerprint` column has a unique constraint; insert collisions are silently skipped (logged and counted, not raised).

The upload report (already produced by slice 02) is extended to surface the count of skipped duplicates: `"47 imported, 12 duplicates skipped"`.

The description normalization rule lives entirely inside `Fingerprinter` (lowercase, collapse whitespace, strip noise). The Counterparty key normalization rule lives entirely inside `CounterpartyKeyNormalizer` and is *also* used later by Merchant Memory (slice 09); keeping it in its own module avoids duplicating the rules in two places.

This slice handles both forms of duplicate that real-world ingest produces:

- **Identical re-uploads.** The same PDF dropped twice. File-hash dedup at the Statement level (already in `statements.source_file_sha256` from slice 03) catches this — confirm it works end-to-end.
- **Overlapping Statements.** A March-only PDF and a Q1 PDF both contain March transactions. File hashes differ, but the per-Transaction Fingerprints collide; the second Statement's March rows are skipped.

The legitimate-duplicate edge case (two genuinely distinct same-day same-amount same-description Transactions) is accepted: the second one will be wrongly dropped. This trade-off was settled during design grilling and is not revisited here.

## Acceptance criteria

- [ ] `Fingerprinter.fingerprint(account_id, booking_date, amount_cents, description) → str` is a pure function
- [ ] `CounterpartyKeyNormalizer.key(iban: Optional[str], name: str) → str` is a pure function
- [ ] `transactions.fingerprint` has a unique index; insert collisions are silently skipped
- [ ] Re-uploading the exact same PDF: file-level dedup rejects it before extraction (slice 03 already handles this — verify still works)
- [ ] Uploading two overlapping Statements (e.g. March-only and Q1): March Transactions appear once in the DB
- [ ] Upload report includes "N imported, M duplicates skipped"
- [ ] Table-driven tests for `Fingerprinter`: identical inputs produce identical fingerprints; whitespace and casing differences in description do not break dedup; distinct transactions do not collide
- [ ] Table-driven tests for `CounterpartyKeyNormalizer`: IBAN-present, IBAN-absent, GmbH/AG/SE suffix stripping, casing, whitespace, common bank-printed noise

## Blocked by

- Slice 03 (PDF Extraction + Reconciliation Gate)
