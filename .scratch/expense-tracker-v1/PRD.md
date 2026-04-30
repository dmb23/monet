# PRD: Expense Tracker v1

Status: needs-triage

## Problem Statement

Tracking expenses across several bank accounts (potentially belonging to different members of a household) is currently a manual exercise: PDFs are downloaded, transactions are read by eye or copy-pasted into a spreadsheet, and categorization is repetitive and error-prone. Existing personal-finance tools either require uploading bank data to a cloud service (unacceptable on privacy grounds) or require manual data entry (defeats the purpose).

## Solution

A local-only Python application that watches a folder for bank statement PDFs, parses them with a locally-running LLM, validates each statement against its own opening/closing balance, stores the resulting transactions in DuckDB, and surfaces categorized spending through a server-rendered web dashboard. No data leaves the user's machine. Categorization runs asynchronously after ingest using the same local LLM, with a deterministic Merchant Memory layer that learns from manual corrections so the LLM only handles unseen counterparties.

## User Stories

1. As a household tracker, I want to drop a bank statement PDF into a configured folder, so that the file gets processed without my having to open the app first.
2. As a household tracker, I want the system to identify which Account a PDF belongs to by extracting the IBAN, so that I do not have to label uploads manually.
3. As a household tracker, I want to be prompted to register a new Account the first time an unknown IBAN appears, so that onboarding a new account is a single step.
4. As a household tracker, I want each Account to carry an Owner label, so that I can filter the dashboard to "what Anna spent" or "what Ben spent".
5. As a household tracker, I want every parsed Statement to be validated against its printed opening and closing balances, so that silent extraction errors do not poison my dashboard data.
6. As a household tracker, I want a Statement that fails reconciliation to leave none of its Transactions committed, so that I never see partial or corrupted data on the dashboard.
7. As a household tracker, I want a failing PDF to remain in the Inbox with a sidecar `.error.json` describing the diff, so that I have everything I need on disk to diagnose and retry.
8. As a household tracker, I want the dashboard to surface a banner when one or more Statements need review, so that failures cannot go unnoticed.
9. As a household tracker, I want successfully ingested PDFs to be moved into a Processed Archive structured as `processed/<year>/<account-name>/`, so that the Inbox always reflects work that still needs my attention.
10. As a household tracker, I want each Transaction to be uniquely identified by a deterministic Fingerprint of `(account_id, booking_date, amount, normalized_description)`, so that the same transaction never gets double-counted across overlapping or re-uploaded Statements.
11. As a household tracker, I want a count of skipped duplicates surfaced in the per-upload report, so that I can confirm dedup is working as expected.
12. As a household tracker, I want internal transfers between two Accounts I own to be detected automatically by counterparty IBAN match, so that I do not have to mark them manually.
13. As a household tracker, I want Transfer-kind Transactions to be excluded from spending and income totals on the dashboard by default, so that net figures are not double-counted.
14. As a household tracker, I want every Transaction's `Kind` to be derived from a clear pipeline (sign rule, then IBAN match override), so that the rules are predictable and inspectable.
15. As a household tracker, I want each Transaction (other than Transfers) to be assigned a Category drawn from a flat, pre-seeded list, so that spending breakdowns are immediately useful.
16. As a household tracker, I want categorization to run asynchronously after ingest, so that the upload feels instant even though the local LLM is slow.
17. As a household tracker, I want the dashboard to show how many Transactions are still being categorized in the background, so that I can tell when the system is busy.
18. As a household tracker, I want the LLM to be allowed to return `Uncategorized` rather than guessing, so that a confident-but-wrong label never hides in my dashboard.
19. As a household tracker, I want the LLM to choose only from the existing Category list, so that the taxonomy doesn't sprawl with `Coffee`, `Cafes`, `Coffee Shops` as separate categories.
20. As a household tracker, I want the system to remember my manual category correction per Counterparty, so that I never have to correct the same merchant twice.
21. As a household tracker, I want Merchant Memory to be updated only on the first manual correction for a Counterparty, so that occasional one-off overrides (a TV bought at a grocery store) don't overwrite the dominant rule.
22. As a household tracker, I want Merchant Memory to be the first lookup before any LLM call during categorization, so that ingest performance improves dramatically as the system learns my merchants.
23. As a household tracker, I want to manually correct a Transaction's `Category` in the UI, so that I can clean up LLM misclassifications without re-running the pipeline.
24. As a household tracker, I want to manually override a Transaction's `Kind` in the UI, so that I can fix the rare case where IBAN extraction missed a Transfer or misread a Refund.
25. As a household tracker, I want all other Transaction fields (description, amount, dates, counterparty) to be read-only post-ingest, so that the data on the dashboard always traces back to a single source of truth.
26. As a household tracker, I want a "Reingest Statement" action that deletes a Statement, moves its PDF back to the Inbox, and triggers re-extraction, so that fixing extraction errors is a one-click flow.
27. As a household tracker, I want my Merchant Memory entries to survive a Reingest Statement, so that recurring counterparties auto-recover their categories on the second pass.
28. As a household tracker, I want to add, rename, or delete Categories from the global list, so that the taxonomy reflects my actual spending shape over time — except `Uncategorized`, which I want to be permanent.
29. As a household tracker, I want a record of every Category change on a Transaction (with source: `llm`, `memory`, or `user`), so that the system can correctly distinguish first-time corrections from later overrides.
30. As a household tracker, I want my dashboard to default to the current calendar month, so that the first thing I see matches the cadence at which statements arrive.
31. As a household tracker, I want the dashboard to show a Category breakdown for the selected period, so that I can see at a glance where money is going.
32. As a household tracker, I want to filter the dashboard by Owner, Account, Kind, Category, Counterparty, and date range, so that I can answer specific questions like "what has Anna spent on groceries this year".
33. As a household tracker, I want to drill down from any Category in the dashboard into the underlying Transaction list, so that I can verify the breakdown against actual transactions.
34. As a household tracker, I want the application to run entirely on my local machine, so that no financial information leaves my device.
35. As a household tracker, I want the local LLM to be replaceable behind a single port, so that I can swap models or runtimes without rewriting the categorization or extraction logic.

## Implementation Decisions

### Tech stack

- **Language:** Python.
- **Storage:** DuckDB (single-file, embedded; well-suited to analytical dashboard queries).
- **Local LLM runtime:** vLLM, exposed via its OpenAI-compatible HTTP API. Requires CUDA-capable GPU as a hardware prerequisite — flag this in setup docs.
- **Web framework:** Server-rendered (e.g. FastAPI or Flask) + HTMX for interactivity. No SPA, no separate frontend codebase.
- **PDF text extraction:** `pdfplumber` or `pypdf` for the raw text-extraction step that feeds the LLM.
- **File watching:** `watchdog` library.

### Module decomposition

Deep modules (small interfaces, big internals, tested in isolation):

- **`PDFExtractor`** — `extract(pdf_bytes) → ExtractionResult { account_iban, opening_balance, closing_balance, transactions[] }`. v1 has a single `LLMExtractor` implementation; future per-bank parsers slot in behind the same interface. The LLM is reached through an injected `LLMPort`, which is what makes vLLM swappable.
- **`ReconciliationValidator`** — `validate(ExtractionResult) → Outcome`. Pure function. Implements ADR-0001 (binary commit semantics).
- **`Fingerprinter`** — `fingerprint(account_id, booking_date, amount_minor, description) → str`. Pure function. Owns the description-normalization rule.
- **`CounterpartyKeyNormalizer`** — `key(iban?, name) → str`. Pure function. Used by both `Fingerprinter` and the Merchant Memory lookup. Normalization rules (lowercase, collapse whitespace, strip common legal-form suffixes when no IBAN is present) live here exclusively.
- **`KindClassifier`** — `classify(transaction, own_account_ibans) → Kind`. Pure function implementing the sign rule + IBAN-match override pipeline from CONTEXT.md.
- **`CategoryResolver`** — `resolve(transaction, *, memory: MerchantMemoryPort, llm: LLMPort) → (category, source)`. Implements the Merchant-Memory-first / LLM-fallback pipeline. Both ports are injected, so this module can be tested with simple stubs.

Coordination / plumbing modules:

- **`IngestionOrchestrator`** — chains: extract → reconcile → dedup → kind classify → commit → enqueue categorization. Returns an `IngestOutcome` of `committed` or `needs_review`.
- **`InboxWatcher`** — emits new-file events; manages sidecar `.error.json`; performs the move to the Processed Archive on success and back to Inbox on Reingest.
- **`Repositories`** — one per entity (`Account`, `Statement`, `Transaction`, `Category`, `MerchantMemory`, `CategoryHistory`), each thinly wrapping DuckDB.
- **`WebUI`** — dashboard, Category editor, manual `Category`/`Kind` overrides, Reingest Statement action.

### Schema (DuckDB)

Tables (column lists are indicative, not exhaustive):

- `accounts` — `id`, `iban` (unique), `name`, `owner_label`, `bank_name`.
- `statements` — `id`, `account_id` (FK), `source_file_path`, `source_file_sha256` (unique), `period_start`, `period_end`, `opening_balance_cents`, `closing_balance_cents`, `status` ∈ {`ingested`, `needs_review`}, `ingested_at`.
- `transactions` — `id`, `statement_id` (FK), `account_id` (FK, denormalized for query speed), `fingerprint` (unique), `booking_date`, `value_date`, `amount_cents`, `description`, `counterparty_iban`, `counterparty_name`, `kind` ∈ {`Expense`, `Income`, `Transfer`}, `category_id` (FK, nullable).
- `categories` — `id`, `name` (unique), `is_uncategorized` (boolean, true for the singleton).
- `merchant_memory` — `counterparty_key` (unique), `category_id`, `created_at`.
- `category_history` — append-only log of every Category change per Transaction, with `source` ∈ {`llm`, `memory`, `user`} and `changed_at`.

### Behavioural guarantees from ADRs

- **ADR-0001:** Reconciliation Gate is mandatory and binary. Failed Statements commit nothing.
- **ADR-0002:** No `persons` table — Owner is a free-form string label on Account.
- **ADR-0003:** Merchant Memory is deterministic memoization; the LLM is never fine-tuned on user corrections. Memory updates only on first manual correction per Counterparty.
- **ADR-0004:** Only `Category` and `Kind` are editable post-ingest. All other corrections go through Reingest Statement.
- **ADR-0005:** EU/SEPA-only: hardcoded EUR currency and IBAN-as-identity are intentional, not oversights.

### Asynchronous categorization

Categorization runs in a background worker process (or thread, depending on what fits cleanly with the chosen web framework). The work queue is just a DuckDB table — no Redis, no Celery — kept in-process. Transactions are committed as `category_id = NULL` and the dashboard renders them under the `Uncategorized` bucket with a "still processing" hint until the worker fills them in.

### Pre-seeded Categories

On first run, seed the `categories` table with a small starter set: `Groceries`, `Rent`, `Utilities`, `Transport`, `Dining Out`, `Entertainment`, `Healthcare`, `Salary`, `Subscriptions`, `Cash`, `Other`, plus the permanent `Uncategorized`. The user edits this list freely from the UI thereafter.

## Testing Decisions

### What makes a good test in this codebase

Tests target **external behaviour at module boundaries**, not internals. A `Fingerprinter` test fixes the input/output contract; it does not assert on which hashing library is used. A `PDFExtractor` test pins the parsed result for a sample bank PDF; it does not assert which LLM prompt was sent. This keeps tests durable across implementation changes and makes the deep modules genuinely interchangeable behind their interfaces.

No browser-driven or end-to-end tests in v1. The web UI is exercised by manual use during development; automated tests focus on the data-model and pipeline logic where bugs are silent and expensive.

### Modules with test coverage in v1

| Module | Test priority | Test shape |
|---|---|---|
| `PDFExtractor` | High | Golden-file fixtures: real PDFs from each in-scope bank, expected `ExtractionResult` checked into the repo. Run against the real LLM in a smoke job; against a recorded LLM response in unit tests. |
| `ReconciliationValidator` | High | Table-driven tests covering: balanced statement, off-by-€0.01, off-by-cents, sign-flipped row, missing row. |
| `Fingerprinter` | High | Table-driven tests covering: identical inputs produce identical fingerprint, whitespace/case differences in description don't break dedup, distinct transactions don't collide. |
| `CounterpartyKeyNormalizer` | High | Table-driven tests for IBAN-present vs IBAN-absent, GmbH/AG suffix stripping, whitespace, casing, common bank-printed noise. |
| `KindClassifier` | Medium | Pipeline tests: positive amount → Income, negative → Expense; counterparty IBAN matching own Account → Transfer overrides. |
| `CategoryResolver` | Medium | Tests with a stub `MerchantMemoryPort` and stub `LLMPort`: memory hit short-circuits LLM, memory miss invokes LLM, LLM returning unknown category falls back to `Uncategorized`. |
| `IngestionOrchestrator` | Medium | Two integration tests: (1) happy path commits a Statement and its Transactions; (2) reconciliation failure leaves nothing committed and writes the sidecar `.error.json`. Run against an in-memory DuckDB. |
| `Repositories` | Low | Smoke tests confirming DuckDB-backed implementations satisfy each port's contract. |
| `InboxWatcher` | Low | Filesystem-driven test against a temp directory: drop a file, observe event; ingest succeeds, observe move to archive. |
| `WebUI` | Skip in v1 | Manual exercise during development. |

### Prior art

No existing codebase to reference for prior art (this PRD scaffolds v1 from scratch). The patterns above (port/adapter for swappable infrastructure, pure-function deep modules with table-driven tests, golden-file fixtures for parser-style modules) are conventional Python-stack practices and should be followed throughout.

## Out of Scope

- Non-EU / non-SEPA bank accounts. ADR-0005 explains why this is more than a passing constraint.
- Multi-currency support. Tied to the above; explicitly deferred.
- Authentication or multi-user. The application assumes a single trusted operator on the local machine.
- Manual transaction entry (cash spending, crypto, manual adjustments). The PDF is the only source of Transaction data in v1.
- A transaction-level editor UI (editing description, amount, date, or counterparty). ADR-0004 makes this a deliberate non-goal.
- Mobile or native applications.
- Cloud sync, backup, or multi-device replication.
- Per-Owner taxonomies for Categories. Categories are global (ADR-0002).
- LLM fine-tuning or training infrastructure. Merchant Memory replaces this (ADR-0003).
- SPA frontend. HTMX-only is the chosen complexity ceiling.
- Hand-rolled per-bank PDF parsers. They are explicitly *allowed* by the `PDFExtractor` interface but are not built in v1; the LLM-based extractor is the only implementation shipped.
- Browser-driven end-to-end tests.

## Further Notes

- **Hardware prerequisite:** vLLM expects a CUDA-capable GPU. This needs to be in the README's setup section. If a user without a GPU wants to run the project, they'll need to swap the `LLMPort` adapter for an Ollama-backed or `llama.cpp`-backed implementation — the architecture supports this but no second adapter ships in v1.
- **DuckDB vs SQLite trade-off:** DuckDB was chosen over SQLite for its analytical query strength on dashboard rollups (group-by-category, sum-by-month). DuckDB has weaker write-concurrency, but with a single user and serialized ingest there is no contention. If write contention ever becomes a concern (e.g. concurrent watcher + UI writes), revisit.
- **Pre-seeded category list** is a v1 starter set — expect it to be tuned during early use. The list itself is not a load-bearing decision; the *fact* of pre-seeding (versus starting empty) is what was settled during design.
- **Counterparty key normalization rules** are deliberately concentrated in `CounterpartyKeyNormalizer`. If Merchant Memory false-positives or false-negatives ever surface, this module is the only place to look — and the table-driven tests there are where the regression should be added.
- **The category history table is consulted by Merchant Memory's update rule.** Specifically: a manual correction writes to Merchant Memory only if the most recent prior history row had `source ∈ {llm, memory}` (i.e. this is the *first* user correction for that Counterparty). Subsequent user corrections do not overwrite. This logic lives in `CategoryResolver` (or wherever category mutations are handled) and should be unit-tested.
- **Future extensibility points** baked into the v1 architecture: per-bank parsers behind `PDFExtractor`, alternative LLM runtimes behind `LLMPort`, alternative storage behind the repository ports. These are not features — they are seams. Resist filling them in until a concrete need emerges.
