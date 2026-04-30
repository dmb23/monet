# Async LLM Categorization

Status: needs-triage
Type: HITL
User stories covered: 16, 17, 18, 19

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Add an async categorization worker that picks up Transactions where `category_id IS NULL AND kind != 'Transfer'`, calls the local LLM with `(description, amount, counterparty_name, current Category list)`, and writes the resulting `category_id` back. The LLM is constrained to choose a Category from the existing list or return `Uncategorized`; it does not invent new Categories.

Categorization runs *after* the Reconciliation Gate passes and Transactions are committed (per [ADR-0001](../../../docs/adr/0001-reconciliation-gate-is-mandatory-and-binary.md), nothing un-reconciled is committed). Transactions briefly appear on the dashboard as `Uncategorized` with a "still processing: N" indicator while the worker drains the queue.

The work queue is a DuckDB table — no Redis, no Celery, no separate service. The worker can be in-process (a thread or task started alongside the web server) or a separate process; either is fine. It must be durable across restarts: pending work is the set of `category_id IS NULL` non-Transfer Transactions, recovered from the DB at startup.

The LLM is reached through the existing `LLMPort` (introduced in slice 03), so the same vLLM adapter is reused. `CategoryResolver` is the module that owns the categorization pipeline; in this slice it consists of a single LLM call (Merchant Memory arrives in slice 09).

This slice is HITL because the prompt design (how the LLM is told to constrain its output to the current Category list) and the worker architecture both need human review before merge.

## Acceptance criteria

- [ ] Background worker started alongside the web server; picks up `category_id IS NULL AND kind != 'Transfer'` Transactions
- [ ] LLM call uses the existing `LLMPort`; the v1 vLLM adapter is reused
- [ ] Prompt is constrained: the LLM MUST return a name from the current Category list or the literal string `Uncategorized`; any other response falls back to `Uncategorized`
- [ ] `CategoryResolver.resolve(transaction, *, llm: LLMPort) → (category_id, source: 'llm')` is the single entry point; no Memory layer yet
- [ ] Worker is durable: a process restart with pending work resumes processing without manual intervention
- [ ] Dashboard displays a "still processing: N" indicator that decreases as the worker progresses; the count comes from a SQL query, not in-memory state
- [ ] Unit tests for `CategoryResolver` with stub `LLMPort`: returns valid category, returns unknown name (falls back to `Uncategorized`), returns existing `Uncategorized` directly
- [ ] HITL gate: prompt design and worker architecture reviewed before merge

## Blocked by

- Slice 07 (Categories — Seed + Manual Assignment)
