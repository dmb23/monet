# PDFs are the source of truth; Transaction data is read-only post-ingest

The only Transaction fields editable in the UI are `Category` and `Kind` — both inferred at ingest, so editing them corrects an inference rather than altering source data. Every other field (`description`, `amount`, `booking_date`, `value_date`, `counterparty_iban`, `counterparty_name`) is immutable. To correct any of these, the user invokes Reingest Statement, which cascade-deletes the Statement and moves the PDF back to the Inbox to re-extract.

The natural product impulse is to allow inline editing of every field ("just let me fix this row"). It was rejected because allowing manual edits to source-derived fields creates a class of silent divergence: the database row no longer matches what re-extracting the PDF would produce, and there is no clean rule for whether re-ingest should overwrite, ignore, or merge with the human edit. By making the PDF authoritative, the only way to update is to re-derive — which keeps the data model consistent and makes parser improvements (better LLM, hand-rolled bank parser) safely re-runnable across the historical corpus.

## Consequences

- One-off per-Transaction Category overrides are lost on Reingest Statement. Merchant Memory entries (the dominant signal) are preserved, so frequently-seen counterparties auto-recover.
- There is no "transaction editor" UI in v1 and there shouldn't be one in v2 unless the source-of-truth principle is explicitly revisited.
- A user who needs to record a transaction the bank didn't issue (cash spending, crypto, manual adjustments) is not supported. This is an accepted gap.
