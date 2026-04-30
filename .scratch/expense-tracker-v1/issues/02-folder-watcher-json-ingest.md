# Folder Watcher + JSON Ingest

Status: needs-triage
Type: AFK
User stories covered: 1, 9

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

An `InboxWatcher` that monitors a configured Inbox directory. When a JSON file appears with the shape of an `ExtractionResult` (`account_iban`, `opening_balance`, `closing_balance`, `transactions[]`), the system commits its Transactions to the DB, moves the file to the Processed Archive (`processed/<year>/<account-name>/`), and writes an upload report (count of Transactions committed).

This slice deliberately uses JSON drop-in instead of real PDF parsing so that the watcher and archive plumbing can be validated without an LLM dependency. The Account must already exist in the DB (seeded by slice 01); IBAN lookup matches the JSON to the Account. Slice 03 will replace JSON ingest with the real `PDFExtractor`.

No reconciliation, no fingerprinting, no Kind classification, no categorization. Just: file appears → Transactions land → file is archived.

If the IBAN in the JSON doesn't match any registered Account, the file remains in the Inbox with a sidecar `.error.json` describing "unknown IBAN" — slice 04 replaces this with a registration prompt.

## Acceptance criteria

- [ ] Inbox directory path is configurable
- [ ] Dropping a `.json` ExtractionResult fixture into the Inbox triggers ingest within a few seconds
- [ ] Transactions in the file are committed to the DB against the matching Account (looked up by IBAN)
- [ ] On success, the source file is moved from the Inbox to `processed/<year>/<account-name>/`
- [ ] An upload report (logged to stdout and a per-file `.report.json` next to the archived file) lists the count of Transactions committed
- [ ] Dropping a JSON with an unknown IBAN does NOT commit anything; the file remains in the Inbox with a sidecar `.error.json` describing the problem
- [ ] Integration test: drop a fixture JSON into a temp Inbox; assert resulting DB rows and archive location
- [ ] Unit tests for the IBAN-lookup path

## Blocked by

- Slice 01 (Tracer Skeleton)
