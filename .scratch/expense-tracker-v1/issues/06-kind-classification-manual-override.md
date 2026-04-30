# Kind Classification + Manual Override

Status: needs-triage
Type: AFK
User stories covered: 12, 13, 14, 24

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

At ingest, every Transaction is assigned a `Kind` ∈ {`Expense`, `Income`, `Transfer`} via `KindClassifier`:

1. **Sign rule:** `amount > 0` → tentatively `Income`; `amount < 0` → tentatively `Expense`.
2. **IBAN match override:** if `counterparty_iban` matches the IBAN of any registered own Account → `Kind = Transfer`.

The dashboard excludes `Transfer`-kind Transactions from spending and income totals by default. Internal transfers between two Accounts the user owns therefore stop double-counting.

The UI gains a per-Transaction `Kind` dropdown so the user can manually override the classifier — useful for the rare case where the LLM missed a `counterparty_iban` and a Transfer was misclassified as Expense, or for marking a friend's payback as Transfer if the user prefers it not count as Income. Per [ADR-0004](../../../docs/adr/0004-pdfs-are-source-of-truth-transactions-are-read-only.md), `Kind` is one of only two editable fields on a Transaction; everything else remains read-only.

## Acceptance criteria

- [ ] `KindClassifier.classify(transaction, own_account_ibans) → Kind` is a pure function
- [ ] At ingest, every Transaction has a `kind` value; `Transfer` is set for any Transaction whose `counterparty_iban` matches an own Account
- [ ] Dashboard totals (spend, income) exclude `kind = Transfer` rows
- [ ] UI: per-Transaction Kind dropdown allows manual change; change persists across reload
- [ ] Table-driven tests for `KindClassifier`: positive/negative sign, IBAN match overrides, no IBAN extracted (defaults to sign rule)
- [ ] Integration test: ingest a Statement containing one leg of a transfer between two of the user's own Accounts; verify `Kind = Transfer` on that row

## Blocked by

- Slice 05 (Fingerprint-Based Dedup)
