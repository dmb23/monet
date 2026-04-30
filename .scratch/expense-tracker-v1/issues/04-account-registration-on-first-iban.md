# Account Registration on First IBAN

Status: needs-triage
Type: AFK
User stories covered: 3, 4

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

When extraction yields an IBAN that is not yet in the `accounts` table, the ingest pipeline does not commit the Statement. Instead, the system surfaces a registration prompt in the web UI: the user provides a friendly Account name (e.g. "Anna Checking"), an Owner label (e.g. "Anna"), and a bank name. After the user submits the form, the Account row is created and the watcher retries ingest automatically.

Subsequent Statements for the same IBAN are recognised on first sight and ingest without any prompt.

The Owner label is a free-form string per [ADR-0002](../../../docs/adr/0002-owner-is-a-label-not-a-person-entity.md) — there is no Person entity, no normalization rules. Joint accounts use composite labels like `"Anna+Ben"`.

## Acceptance criteria

- [ ] When a PDF is extracted and its IBAN matches no existing Account, ingest is paused; the Statement does not commit
- [ ] The web UI surfaces a "pending registration" entry showing the extracted IBAN and (if extractable) the bank name
- [ ] The registration form captures: Account name, Owner label, bank name; submission creates the Account row
- [ ] After registration, the watcher re-attempts ingest for the pending PDF; on success, the Statement commits via the normal path (Reconciliation Gate, etc.)
- [ ] Subsequent PDFs for the same IBAN ingest with no prompt
- [ ] Integration test: drop a PDF for a new IBAN, observe the pending state; submit the registration form via the test client; assert the Statement and its Transactions land in the DB

## Blocked by

- Slice 03 (PDF Extraction + Reconciliation Gate)
