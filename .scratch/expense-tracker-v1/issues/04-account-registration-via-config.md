# Account Registration via Config

Status: needs-triage
Type: AFK
User stories covered: 3, 4

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Accounts are declared in a top-level `accounts.toml` file. Each entry is a tuple `(filename_pattern, parser, iban, account_name, owner_label, bank_name)`. On application startup, the config is loaded and the `accounts` table is reconciled against it: for each registration, an `accounts` row is created if it doesn't already exist (matched by IBAN), and existing rows are updated in place if their non-key fields (account_name, owner_label, bank_name) have changed in config. Rows for IBANs no longer in config are left alone (we never silently delete account data).

This replaces the original "drop a PDF, get prompted to register the unknown IBAN" UX from the previous v1 plan. Per [ADR-0006](../../../docs/adr/0006-pdf-extraction-is-per-document-type.md), every PDF requires a per-document-type parser, and parsers are bound to IBANs via registrations — so an Account that isn't in `accounts.toml` cannot have its PDFs ingested anyway. Making the registration explicit and config-driven is the honest UX for that constraint.

The Owner label is a free-form string per [ADR-0002](../../../docs/adr/0002-owner-is-a-label-not-a-person-entity.md) — there is no Person entity, no normalization rules. Joint accounts use composite labels like `"Anna+Ben"`.

### Example `accounts.toml`

```toml
[[account]]
filename_pattern = '^1032455006_.*Kontoauszug.*\.pdf$'
parser           = "triodos_kontoauszug"
iban             = "NL00TRIO0000000000"     # placeholder
account_name     = "Triodos Girokonto"
owner_label      = "Anna"
bank_name        = "Triodos Bank"

[[account]]
filename_pattern = '^1032455014_.*Kontoauszug.*\.pdf$'
parser           = "triodos_kontoauszug"   # same parser, different account
iban             = "NL00TRIO0000000001"
account_name     = "Triodos Sparkonto"
owner_label      = "Anna"
bank_name        = "Triodos Bank"

[[account]]
filename_pattern = '^XXXXXXXXXXXXX501_.*Kreditkarten-Umsatzaufstellung.*\.pdf$'
parser           = "triodos_kreditkarte"
iban             = "NL00TRIO0000000002"
account_name     = "Triodos Mastercard"
owner_label      = "Anna"
bank_name        = "Triodos Bank"
```

### Interaction with the PDFExtractor dispatcher

The dispatcher (slice 03) reads its routing table from the same loaded `accounts.toml`. When a PDF arrives whose filename matches no `filename_pattern`, the dispatcher writes an `unknown_document_type` sidecar — the file is *not* paused waiting for a UI registration, because there is no UI registration in v1. The user's fix is: edit `accounts.toml`, restart the app, the watcher picks the PDF up.

## Acceptance criteria

- [ ] `accounts.toml` is loaded at startup from the configured location (default: repo root or a configurable path)
- [ ] On startup, each registration is reconciled into the `accounts` table: new IBAN → new row; existing IBAN with changed `account_name` / `owner_label` / `bank_name` → row updated; missing-from-config IBAN → row preserved (no silent delete)
- [ ] Startup fails fast with a clear error message if `accounts.toml` is malformed (TOML parse error, missing required fields, duplicate IBAN, invalid regex)
- [ ] The `PDFExtractor` dispatcher (slice 03) consumes the same in-memory registration table
- [ ] A worked example `accounts.toml` is checked into the repo (with placeholder IBANs) and referenced from the README's setup section
- [ ] Integration test: start the app with a fixture `accounts.toml` containing two registrations; assert two `accounts` rows are created. Restart with one registration's `owner_label` edited; assert the row is updated. Restart with one registration removed; assert the row remains.
- [ ] Unit tests for the config loader: malformed TOML, missing required field, duplicate IBAN, invalid regex each produce a distinct error message

## Blocked by

- Slice 01 (Tracer Skeleton) — needs the `accounts` table to exist

## Note

The `PDFExtractor` dispatcher in slice 03 depends on this slice for the registration table, but this slice does not depend on slice 03 — it can be built and tested first against a stub dispatcher that just reads the table. Slice 03's blocker on this one is the real coupling.
