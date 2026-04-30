# Expense Tracker

A local-only application that ingests bank-account PDF statements, stores their transactions in a structured form, and presents categorized spending via a web dashboard. No data leaves the user's machine.

## Language

**Account**:
A bank account whose PDF statements are ingested into the system. Each Account carries an **Owner** label.
_Avoid_: User (no login concept exists)

**Owner**:
A free-form string label on an **Account** identifying which person that account belongs to. Not a first-class entity — just metadata used for filtering and attribution.
_Avoid_: Person, User, Holder

**Statement**:
A single PDF file representing one bank-issued account summary, covering a date range. Statements are the unit of ingestion.
_Avoid_: Document, Sheet, Report

**Transaction**:
A single line item parsed out of a **Statement** — one debit or credit on an **Account**. The atomic unit of analysis. Uniquely identified by a **Fingerprint** computed at ingest.
_Avoid_: Entry, Line, Posting, Booking

**Fingerprint**:
A deterministic hash of `(account_id, booking_date, amount_cents, normalized_description)` used to dedupe **Transactions** across re-uploaded or overlapping **Statements**. On ingest, a Transaction whose Fingerprint already exists is silently skipped; the count of skipped duplicates is surfaced in the upload report.
_Avoid_: Hash, Key, ID

**Reconciliation Gate**:
A pre-commit check applied to every parsed **Statement**: `opening_balance + sum(transactions) == closing_balance` (within €0.01). A Statement that fails the gate is flagged `needs_review` and **none** of its Transactions are committed. The dashboard surfaces failed Statements explicitly.
_Avoid_: Validation, Verification, Check

**Needs Review**:
A state on a **Statement** indicating it failed the **Reconciliation Gate**. Realised in practice as: the PDF stays in the **Inbox** with a sidecar `.error.json` describing the diff. The user resolves it by re-triggering ingest (after a transient failure) or by patching the LLM prompt / adding a hand-rolled parser, then re-dropping the file. No Transactions from a Needs Review Statement are visible in the dashboard.
_Avoid_: Failed, Error, Pending

**Inbox**:
A configurable filesystem directory watched by the ingest pipeline. PDFs land here (manually copied, or via external automation). Files awaiting ingest and files that failed the **Reconciliation Gate** both live here; the latter are paired with a sidecar `.error.json`. Successful ingest moves the PDF to the **Processed Archive**.
_Avoid_: Watch folder, Drop folder, Queue

**Processed Archive**:
The directory `processed/<year>/<account-name>/` where successfully-ingested PDFs are moved. Treated as the source of truth — never edited in place. Re-ingest of an existing **Statement** happens by **Reingest Statement**, which moves the PDF back to the **Inbox**.
_Avoid_: History, Done folder

**Reingest Statement**:
A destructive UI action that, atomically: cascade-deletes a **Statement** (and all its **Transactions**), moves the original PDF from the **Processed Archive** back to the **Inbox**, and triggers the watcher to retry. The only supported way to correct extraction errors in fields other than **Category** and **Kind**. **Merchant Memory** entries survive across Reingest, so frequently-seen Counterparties auto-recover their Categories on the second pass; one-off per-Transaction overrides are lost.
_Avoid_: Re-import, Reset, Refresh

**Kind**:
A first-class field on every **Transaction**, one of: `Expense`, `Income`, `Transfer`. Determines whether the Transaction counts toward spending/earning totals. `Transfer` covers movements between two Accounts the user owns and is excluded from spend/income aggregates by default. (Refunds are stored as `Income` in v1 — not modeled separately.)
_Avoid_: Type, Direction

**Category**:
A label assigned to a **Transaction** describing what it was for (e.g. `Groceries`, `Rent`). Drawn from a single flat list (no hierarchy, no multi-tag). Only meaningful when **Kind** is `Expense` or `Income`; ignored for `Transfer`.
_Avoid_: Tag, Group, Bucket

**Counterparty**:
The other party in a **Transaction**, as printed on the **Statement**. Recorded as `(counterparty_iban, counterparty_name)` on every Transaction. Used both for **Transfer** detection (IBAN match against own Accounts) and for grouping in the dashboard.
_Avoid_: Recipient, Sender, Payee

**Merchant Memory**:
A learned mapping `Counterparty → Category` built from the user's manual category corrections. When a new **Transaction** arrives whose Counterparty key already has an entry in Merchant Memory, the stored Category is auto-applied without invoking the LLM. The mapping updates only when the user manually corrects a Transaction whose Counterparty isn't yet in memory; subsequent per-transaction overrides do not modify it.
_Avoid_: Rule, Heuristic, Auto-categorizer

## Relationships

- An **Account** has exactly one **Owner** label
- An **Account** is uniquely identified by its IBAN
- A **Statement** belongs to exactly one **Account**
- A **Statement** contains zero or more **Transactions**
- A **Transaction** has exactly one **Kind**
- A **Transaction** has zero or one **Category** (zero when Kind is Transfer or Refund)
- A **Transaction**'s canonical date is its **Buchungstag** (booking date). Wertstellungstag (value date) is recorded but does not drive Fingerprint or aggregations.

## Kind assignment pipeline

Applied to every **Transaction** at ingest, in order:

1. **Sign rule** sets the default: `amount > 0` → `Income`; `amount < 0` → `Expense`.
2. **IBAN match** overrides: if `counterparty_iban` matches the IBAN of any registered own **Account**, set `Kind = Transfer`.
3. **Kind is settled before categorization runs.** **Category** is only assigned for `Expense` and `Income`.

## Categorization rules

- The **Category** list is global (shared across all **Accounts** and **Owners**).
- It is pre-seeded with a small starter set and is editable only via deliberate user action in the UI.
- The local LLM may only assign Categories from the existing list, or fall back to `Uncategorized`. It does not invent new ones.
- `Uncategorized` is a permanent bucket and cannot be deleted.

## Categorization pipeline (per Transaction, after Kind is settled)

Runs asynchronously after the **Reconciliation Gate** passes and Transactions are committed. Skipped when Kind is `Transfer`.

1. **Merchant Memory lookup.** If the Transaction's Counterparty key has a stored Category, apply it. Done — no LLM call.
2. **LLM call.** Otherwise, call the local LLM with `(description, amount, counterparty_name, current Category list)`. The LLM returns one of the existing Categories or `Uncategorized`.
3. **No new categories.** The LLM cannot create Categories; only the user can, via deliberate UI action.

## Mutability rules

- **Editable on a Transaction:** `Category`, `Kind`. These are inferred fields — the user is correcting an inference, not altering source data.
- **Immutable on a Transaction:** `description`, `amount`, `booking_date`, `value_date`, `counterparty_iban`, `counterparty_name`. The PDF is the authority; to correct any of these, **Reingest Statement**.
- **Audit trail:** every change to a Transaction's Category is appended to a category history table with `(category, source: llm | memory | user, changed_at)`. Required so **Merchant Memory** can distinguish first-time user corrections (which write to memory) from subsequent overrides (which don't).

## Scope assumptions

- **EU/SEPA only.** All Accounts are with EU banks; identity is IBAN, currency is EUR. Non-EU banks would invalidate the IBAN-as-identity model and force multi-currency. Out of scope for v1.

## Flagged ambiguities

- A **joint account** (two real-world owners) under the current model gets a single composite Owner label (e.g. `"Anna+Ben"`). Per-person rollups across joint and personal accounts are therefore not possible without changing the model. Accepted trade-off.
