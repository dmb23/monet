# PDF extraction is per-document-type, not model-driven

PDF extraction in v1 is performed by per-document-type Python modules using `camelot` (or equivalent) with hand-tuned layout coordinates. A `PDFExtractor` dispatcher routes each PDF to the correct parser by filename pattern. Account binding is via configured `(filename_pattern, parser, iban, account_name, owner_label)` registrations in `accounts.toml`, loaded at startup. The `LLMPort` seam is retained for categorization only.

The original v1 plan specified a single model-based `PDFExtractor` covering all banks behind one LLM call. During May 2026 we prototyped several model-based parsers — including layout-aware vision-language pipelines (docling) and direct VLM/LLM prompting against the rendered PDF — against real Triodos statements. None came close to clearing the Reconciliation Gate consistently: tables were dropped or merged, amounts were transposed, and sign columns (Soll/Haben) were misread often enough that the Inbox would have routinely filled with `needs_review` files on PDFs the model "should" have parsed. The error mode was not "occasionally wrong" but "wrong in ways that look right" — exactly the silent-extraction class the Reconciliation Gate was designed to catch (see ADR-0001).

We picked per-document-type code-driven extraction because the failure shape inverts: errors are now bounded by code rather than by stochastic model behaviour. When a parser is wrong, it is wrong the same way on every PDF — which makes it fixable in one place, with a regression test pinning the fix. The cost is linear effort per bank/document-type and a developer-style onboarding flow for new accounts.

## Consequences

- Adding support for a new bank or document type is a code change (a new parser module + a new `accounts.toml` registration), not a configuration change alone. Onboarding a new Account is developer-style.
- The "register a new Account by dropping a PDF with an unknown IBAN" UX is dropped. Accounts are declared in `accounts.toml` before their first PDF arrives.
- Extractors are living code: when an edge case surfaces (an unparsed Vorgangstyp, a missing counterparty IBAN, a layout shift), the user extends the extractor with a hard-coded branch and re-ingests. This is the deliberate maintenance posture, not an accident.
- The Reconciliation Gate (ADR-0001) is now guarding against parser bugs in regions the developer didn't anticipate, rather than against general model hallucination. Its role in the pipeline is unchanged.
- Multiple registrations may share one parser module (e.g. a Girokonto parser used by both a current account and a savings account at the same bank). Parser modules know nothing about IBANs; registrations carry the binding.
- Hand-rolled per-bank PDF parsers were listed as out-of-scope in the original PRD. This ADR reverses that explicitly.
