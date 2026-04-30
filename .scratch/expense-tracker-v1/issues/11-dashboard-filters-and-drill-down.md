# Dashboard Filters + Drill-Down

Status: needs-triage
Type: AFK
User stories covered: 30, 31, 32, 33

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Replace the basic "list all Transactions" dashboard from slice 01 with a useful interactive view.

**Default state:** current calendar month, all Owners, all Accounts. The Category breakdown for the period is the headline view; a Transaction list sits alongside.

**Filter dimensions, AND-combined:**

- Owner (free-form labels from registered Accounts)
- Account
- Kind (Expense, Income, Transfer — the latter excluded by default)
- Category
- Counterparty
- Date range

Filters compose: e.g. "Anna's groceries this month" is `Owner = Anna AND Category = Groceries AND date in current month`.

**Drill-down:** clicking a Category in the breakdown narrows the Transaction list to that Category (via the existing filter mechanism). No new page; the filter just gets one more clause.

All filter changes use HTMX swaps — no full page reload.

This is the slice that turns the application from "data is in the DB" into "data is useful". Performance considerations: the dashboard queries are aggregations over `transactions` and should run in tens of milliseconds on DuckDB for personal-finance-scale data; if any query exceeds that, profile and add an index rather than caching.

## Acceptance criteria

- [ ] Default view: current calendar month, all Owners, all Accounts, Transfer kind excluded
- [ ] Filter controls for Owner, Account, Kind, Category, Counterparty, date range — all visible on the dashboard page
- [ ] Filters compose via AND; the URL or form state is the source of truth so a refresh preserves the view
- [ ] Category breakdown chart (bar or pie) for the selected period
- [ ] Transaction list adjacent to the breakdown, filtered identically
- [ ] Click a Category in the breakdown → Transaction list narrows to that Category (filter clause added)
- [ ] HTMX-driven: filter changes update the breakdown and list in place, no full page reload
- [ ] Smoke test: assert the default view returns the current month's Transactions; one parametric test for an Owner+Category filter

## Blocked by

- Slice 07 (Categories — Seed + Manual Assignment) — Categories must exist for filtering by them to be meaningful
