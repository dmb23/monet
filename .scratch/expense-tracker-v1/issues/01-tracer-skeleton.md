# Tracer Skeleton

Status: needs-triage
Type: AFK
User stories covered: 34

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Bootstrap a Python project that runs a web server, connects to a DuckDB database with the v1 schema, and serves a dashboard page listing all Transactions in the database. Provide a small seed script that populates one Account and a handful of Transactions for development.

The point of this slice is not to deliver functionality — it is to prove the local stack (Python + DuckDB + web framework + HTMX + test runner) composes cleanly before any feature work is layered on top. Every subsequent slice depends on this skeleton being solid.

The full v1 schema (tables: `accounts`, `statements`, `transactions`, `categories`, `merchant_memory`, `category_history`) should be created up front, even though only `accounts` and `transactions` are exercised in this slice. This avoids schema migrations during the early slices.

## Acceptance criteria

- [ ] Project boots with a single command (e.g. `python -m <app>`) and serves the dashboard on a local port
- [ ] DuckDB schema for all v1 tables is created on first run if missing; idempotent on subsequent runs
- [ ] A seed script populates one Account and at least 3 Transactions for development use
- [ ] The dashboard page renders the seeded Transactions in a list, including date, description, amount, and account name
- [ ] At least one smoke test runs against the schema (e.g. round-trip insert/read on a Transaction row)
- [ ] No external network calls during normal operation; the application runs entirely on the local machine
- [ ] README documents how to install dependencies, run the server, and run the test suite

## Blocked by

None — can start immediately.
