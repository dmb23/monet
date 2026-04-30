# EU/SEPA-only is a load-bearing v1 constraint

v1 supports only EU/SEPA-area bank accounts. This isn't a passing assumption — it's wired into two foundational decisions: (i) Account identity is the IBAN, which is universal in SEPA but absent in many non-SEPA jurisdictions (US uses routing+account, etc.); (ii) all amounts are stored and displayed in EUR with no FX conversion logic anywhere in the system.

Adding non-EU bank support is therefore not a small extension. It requires generalizing Account identity to a `(country, identifier)` shape (and migrating existing rows), adding a `currency` column to every Transaction, picking and implementing an FX rate policy (transaction-time vs. today's rate vs. no-conversion-show-separate-sums), and updating Transfer detection to handle cross-currency transfers. Each of these has open trade-offs that were not explored in v1.

## Consequences

- Hardcoded `"EUR"` and IBAN-shaped identifiers are deliberate, not oversights. They mark places that would need rework if scope ever expands.
- A future contributor seeing `currency = "EUR"` everywhere should not "fix" it by adding a currency column without simultaneously addressing identity, FX policy, and transfer detection — these are tied.
