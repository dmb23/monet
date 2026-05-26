# Reconciliation Gate is mandatory and binary

Every parsed Statement is checked against `opening_balance + sum(transactions) == closing_balance` (within €0.01) before any of its Transactions are committed. If the check fails, the Statement is flagged `needs_review` and **none** of its Transactions are committed; the PDF stays in the Inbox with a sidecar `.error.json`. There is no "force-commit with warnings" mode.

This is a deliberate constraint, not a v1 placeholder. Even with per-document-type code-driven extraction (ADR-0006), silent extraction errors — dropped rows, swapped digits, sign flips, mis-handled edge cases in unfamiliar Vorgangstypen — remain a persistent risk. The reconciliation gate is the only mechanism that converts those silent errors into loud failures. Allowing partial commit, "best-effort" ingest, or warnings would defeat the gate: bad data would land in the dashboard exactly the way the gate exists to prevent.

## Consequences

- A failed Statement requires manual intervention (re-trigger, or extending the per-document-type parser to cover the edge case). This is acceptable.
- Bank statements where opening/closing balance can't be reliably extracted are not supported. If this occurs in practice, address it by improving extraction — not by relaxing the gate.
