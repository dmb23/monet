SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS seq_accounts_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_categories_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_statements_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_transactions_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_merchant_memory_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_category_history_id START 1;

CREATE TABLE IF NOT EXISTS accounts (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_accounts_id'),
    iban TEXT UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    account_name TEXT,
    bank_name TEXT
);

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_name TEXT;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS bank_name TEXT;

CREATE TABLE IF NOT EXISTS categories (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_categories_id'),
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS statements (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_statements_id'),
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    filename TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    opening_balance INTEGER NOT NULL,
    closing_balance INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'needs_review')),
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE statements ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ok';
ALTER TABLE statements ADD COLUMN IF NOT EXISTS source_file_sha256 TEXT;
CREATE INDEX IF NOT EXISTS idx_statements_sha256 ON statements(source_file_sha256);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_transactions_id'),
    statement_id BIGINT REFERENCES statements(id),
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    fingerprint TEXT NOT NULL,
    booking_date TEXT NOT NULL,
    value_date TEXT,
    amount_cents INTEGER NOT NULL,
    description TEXT NOT NULL,
    counterparty_iban TEXT,
    counterparty_name TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('Expense', 'Income', 'Transfer')),
    category_id BIGINT REFERENCES categories(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, fingerprint)
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS statement_id BIGINT;

CREATE TABLE IF NOT EXISTS merchant_memory (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_merchant_memory_id'),
    counterparty_iban TEXT,
    counterparty_name TEXT NOT NULL,
    category_id BIGINT NOT NULL REFERENCES categories(id),
    UNIQUE(counterparty_iban, counterparty_name)
);

CREATE TABLE IF NOT EXISTS category_history (
    id BIGINT PRIMARY KEY DEFAULT nextval('seq_category_history_id'),
    transaction_id BIGINT NOT NULL REFERENCES transactions(id),
    category_id BIGINT REFERENCES categories(id),
    source TEXT NOT NULL CHECK (source IN ('llm', 'memory', 'user')),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
