# Reingest Statement Action

Status: needs-triage
Type: AFK
User stories covered: 26, 27

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

A destructive UI action on a Statement detail page: cascade-delete the Statement and all of its Transactions, move the source PDF from the Processed Archive (`processed/<year>/<account-name>/`) back to the Inbox, and trigger the watcher to retry. The whole sequence is atomic from the user's perspective — one click, one outcome.

`merchant_memory` and `category_history` are **not** touched. This is what makes the Reingest action ergonomic: Categories for frequently-seen Counterparties are restored automatically on re-extraction via the Memory-first lookup (slice 09). One-off per-Transaction overrides are lost — that is the documented trade-off in [ADR-0004](../../../docs/adr/0004-pdfs-are-source-of-truth-transactions-are-read-only.md).

The UI must make the consequences clear (a confirmation dialog explaining "this will re-extract and may lose per-Transaction overrides"). The action is intentionally destructive — it is the user's escape hatch when extraction got something wrong in a non-`Category`/`Kind` field.

## Acceptance criteria

- [ ] Reingest button on the Statement detail page; confirmation dialog explains the consequences
- [ ] On confirm: the Statement row and all linked Transaction rows are deleted in a single DB transaction
- [ ] The source PDF is moved from `processed/<year>/<account-name>/` back to the Inbox
- [ ] The watcher detects the file and re-runs the slice 03 ingest path (extraction + Reconciliation Gate + commit)
- [ ] Manual `Category`/`Kind` overrides on the previous Transactions are lost (this is expected)
- [ ] Categories restore for Counterparties present in `merchant_memory` (no LLM call needed for those)
- [ ] Integration test: ingest a Statement; manually correct one Counterparty's Category (writes to Memory); Reingest the Statement; assert Categories for that Counterparty are restored from Memory without LLM invocation

## Blocked by

- Slice 09 (Merchant Memory + Audit Trail) — the "Memory survives Reingest" demonstration depends on Memory existing
