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

## Tech Stack

- **Backend**: Python 3.12+, FastAPI (uvicorn)
- **Database**: DuckDB (local, zero-config)
- **Frontend**: HTML + HTMX + Jinja2
- **Testing**: pytest
- **Tooling**: uv

## Data Privacy

All data is stored locally on your machine. No external network calls are made during normal operation.
