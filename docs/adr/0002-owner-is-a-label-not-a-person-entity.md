# Owner is a label on Account, not a first-class Person entity

Each Account has a free-form `owner_label` string (e.g. `"Anna"`, `"Ben"`, `"Anna+Ben"`). There is no `persons` table, no `account_owners` join table, and no entity representing a person.

This was a deliberate choice over the more "normalized" model where Person is an entity and Accounts have one or more Owners. The trade-off accepted: per-person rollups across multiple Accounts (especially across joint and personal accounts) are not possible without changing the model. Joint accounts are represented by composite labels like `"Anna+Ben"` and don't roll up into either individual's totals. For the v1 use case (a household tracking expenses across a small number of accounts), this is fine; if per-person rollups become important later, introducing a Person entity is a contained migration.

## Consequences

- Filtering "show me Anna's spending" works for accounts labelled exactly `"Anna"`, not for joint accounts.
- The Category list is correspondingly global, not per-Owner — a per-Owner taxonomy doesn't fit a label-based ownership model.
- Resist the natural impulse to "normalize this" without a concrete need.
