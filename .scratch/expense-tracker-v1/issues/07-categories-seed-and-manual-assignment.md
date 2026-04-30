# Categories — Seed + Manual Assignment

Status: needs-triage
Type: AFK
User stories covered: 15, 23, 25, 28

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Pre-seed the `categories` table on first run with a starter set: `Groceries`, `Rent`, `Utilities`, `Transport`, `Dining Out`, `Entertainment`, `Healthcare`, `Salary`, `Subscriptions`, `Cash`, `Other`. The permanent `Uncategorized` bucket already exists from slice 01; this slice ensures it cannot be deleted via UI or backend.

The web UI gains a Category management page: list, add, rename, delete Categories — except `Uncategorized`. The dashboard's per-Transaction view gets a Category dropdown for manual assignment.

Per [ADR-0004](../../../docs/adr/0004-pdfs-are-source-of-truth-transactions-are-read-only.md), only `Category` and `Kind` are editable on a Transaction in the UI. All other fields (`description`, `amount`, `booking_date`, `value_date`, `counterparty_iban`, `counterparty_name`) must be displayed read-only — confirm this constraint is enforced by the UI here.

The Category list is global per [ADR-0002](../../../docs/adr/0002-owner-is-a-label-not-a-person-entity.md): there are no per-Owner taxonomies. The LLM does not feature in this slice — automated categorization arrives in slice 08.

## Acceptance criteria

- [ ] First boot creates the pre-seeded list of Categories (in addition to the permanent `Uncategorized`)
- [ ] `Uncategorized` cannot be deleted: the UI omits the delete control for it; the backend rejects deletion attempts
- [ ] User can add, rename, and delete other Categories from the management page; changes are reflected immediately (HTMX swap)
- [ ] Renaming a Category does not require any FK rewrites in `transactions` (use a stable Category id)
- [ ] Per-Transaction Category dropdown in the UI commits manual assignments and persists across reload
- [ ] Read-only display of `description`, `amount`, `booking_date`, `value_date`, `counterparty_iban`, `counterparty_name` — no edit affordance for these fields
- [ ] Tests for Category CRUD endpoints (list, create, rename, delete; delete-Uncategorized rejected)

## Blocked by

- Slice 06 (Kind Classification + Manual Override)
