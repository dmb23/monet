# Othermonet - Expense Tracker

A local-only application that ingests bank-account PDF statements, stores their transactions in a structured form, and presents categorized spending via a web dashboard. No data leaves your machine.

## Installation

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python and dependencies)

### Setup

`uv` reads `.python-version` and `pyproject.toml` and provisions everything on first run — no manual venv or `pip install` step.

```bash
uv sync
```

## Running the Application

```bash
uv run othermonet
```

The application will:
- Initialize the DuckDB database (if it doesn't exist)
- Seed it with sample data (1 Account, 4 Transactions)
- Start the FastAPI server (uvicorn) on `http://127.0.0.1:5000`

Visit `http://127.0.0.1:5000` to see the dashboard.

## Running Tests

```bash
uv run pytest
```

With coverage:
```bash
uv run pytest --cov=othermonet
```

## Project Structure

```
othermonet/
├── src/othermonet/
│   ├── __init__.py
│   ├── app.py          # FastAPI application
│   ├── db.py           # Database connection management
│   ├── schema.py       # DuckDB schema definitions
│   ├── seed.py         # Seed data script
│   ├── templates/      # Jinja2 templates
│   └── static/         # CSS/JS assets
├── tests/              # Test suite
├── data/               # DuckDB database (created on first run)
└── pyproject.toml      # Project configuration (managed by uv)
```

## Adding a new document type

PDF extraction is per-document-type, code-driven (see ADR-0006). To support a
new bank statement layout:

1. **Write a parser module** at `src/othermonet/<bank>_<doctype>.py`. It must
   expose a `DOCUMENT_TYPE` string constant and a
   `parse(pdf_path: Path) -> ExtractionResult` function. Use the
   [`triodos_kontoauszug`](src/othermonet/triodos_kontoauszug.py) module as
   the worked example — it pins `camelot` table areas and column boundaries
   to the Triodos Girokonto layout, parses the `Vorgang` column, and extracts
   counterparty IBAN + name from SEPA-style entries.
2. **Register it** in `src/othermonet/registrations.py` by adding it to the
   `_PARSERS` dict.
3. **Add an `[[account]]` entry** to `accounts.toml` (copy from
   `accounts.toml.example`) binding a filename pattern + the new parser name
   + the account's IBAN and metadata. Multiple `[[account]]` entries may
   share the same parser (e.g. Girokonto + Sparkonto both use
   `triodos_kontoauszug`).
4. **Pin a fixture test** at `tests/test_<parser>.py` — load a real sample
   PDF placed in `tests/fixtures/pdfs/` (gitignored; the test skips when
   the file is missing) and assert period, opening/closing balances,
   transaction count, and that `reconciliation.validate(result).ok`.

Failed PDFs (unknown filename, parser exception, or non-reconciling
balances) stay in the Inbox with a sidecar `.error.json` describing the
failure. The dashboard banner counts them all.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI (uvicorn)
- **Database**: DuckDB (local, zero-config)
- **Frontend**: HTML + HTMX + Jinja2
- **Testing**: pytest
- **Tooling**: uv

## Data Privacy

All data is stored locally on your machine. No external network calls are made during normal operation.
