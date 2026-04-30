# Merchant Memory is deterministic memoization, not adaptive ML

When the user manually corrects the Category of a Transaction whose Counterparty has not been seen before, the system writes a row to a `merchant_memory` table mapping `(counterparty_key → category)`. On future ingests, this lookup runs *before* any LLM call: a hit applies the stored Category instantly and skips the LLM entirely. The LLM is never re-trained or fine-tuned on user corrections.

The natural alternative — feeding corrections back into the LLM as fine-tuning examples — was rejected. Reasons: (i) determinism matters for trust ("REWE is always Groceries unless I say otherwise"); (ii) it eliminates an entire class of training infrastructure that would conflict with the local-only constraint; (iii) it makes the LLM call rate decay quickly as Merchant Memory grows, which is the dominant cost on consumer hardware; (iv) the surprise-factor of an LLM that "drifts" over time is a worse user experience than a memo table the user can inspect and edit.

## Consequences

- The same counterparty always gets the same Category until the user manually overrides on a row that updates Memory (which only happens on the *first* manual correction for that counterparty — subsequent overrides are per-Transaction).
- Edge cases (e.g. REWE for groceries vs. an occasional electronics purchase at REWE) are handled as per-Transaction overrides, not by Memory. This is intentional.
- Merchant Memory survives Reingest Statement — the dominant signal is preserved across re-extractions.
