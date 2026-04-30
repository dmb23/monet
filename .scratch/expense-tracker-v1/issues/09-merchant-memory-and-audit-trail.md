# Merchant Memory + Audit Trail

Status: needs-triage
Type: AFK
User stories covered: 20, 21, 22, 29

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Add the Merchant Memory and Category audit-trail layers on top of the async categorization pipeline from slice 08.

**Schema additions:**

- `merchant_memory` — `(counterparty_key UNIQUE, category_id, created_at)`. The Counterparty key is computed by `CounterpartyKeyNormalizer` (already shipped in slice 05).
- `category_history` — append-only log: `(transaction_id, category_id, source ∈ {'llm', 'memory', 'user'}, changed_at)`. Every Category assignment writes a row.

**`CategoryResolver` is updated** to consult Merchant Memory *before* calling the LLM:

1. **Memory lookup.** If the Transaction's Counterparty key has a row in `merchant_memory`, apply that Category, log to `category_history` with `source = memory`. **No LLM call.**
2. **LLM fallback.** Otherwise, call the LLM as in slice 08, log with `source = llm`.

**The first-time-only Memory update rule** is the key behavior of this slice (per [ADR-0003](../../../docs/adr/0003-merchant-memory-is-deterministic-not-adaptive.md)). When the user manually corrects a Transaction's Category:

- Always: append to `category_history` with `source = user`.
- Conditionally: if `category_history` has no prior row with `source = user` for that Counterparty key, **update or insert the `merchant_memory` row**. Otherwise leave Memory untouched.

This means: the *first* manual correction for a new merchant teaches Memory; any subsequent overrides on individual Transactions of that merchant don't pollute the dominant rule. This is the trade-off behind ADR-0003.

The dashboard immediately benefits: from this slice onward, the LLM call rate decays sharply as Memory grows. Categorization for known counterparties is instant.

## Acceptance criteria

- [ ] Schema: `merchant_memory` and `category_history` tables created
- [ ] `CategoryResolver` consults `merchant_memory` first; on hit, applies the stored Category, logs `source = memory`, makes no LLM call
- [ ] On miss, LLM is called; result is logged with `source = llm`
- [ ] On manual user correction: `category_history` row appended with `source = user`
- [ ] On the first user correction for a Counterparty (no prior `source = user` row in history for that key), `merchant_memory` is inserted/updated
- [ ] On subsequent user corrections for the same Counterparty, `merchant_memory` is NOT modified
- [ ] Unit tests for `CategoryResolver` with stub Memory + stub LLM: memory hit short-circuits LLM, memory miss invokes LLM
- [ ] Unit tests for the first-time-only Memory update rule: a sequence of corrections updates Memory only on the first for a given Counterparty
- [ ] Integration test: ingest a Statement, manually correct one merchant's Category, ingest another Statement containing the same merchant, verify the second pass uses Memory (no LLM call) and gets the corrected Category

## Blocked by

- Slice 08 (Async LLM Categorization)
