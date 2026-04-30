# PDF Extraction + Reconciliation Gate

Status: needs-triage
Type: HITL
User stories covered: 2, 5, 6, 7, 8, 35

## Parent

[Expense Tracker v1 PRD](../PRD.md)

## What to build

Replace the JSON ingest path from slice 02 with a real `PDFExtractor`, backed by an `LLMExtractor` that calls a locally-running vLLM server through an `LLMPort` interface. Every parsed Statement is run through `ReconciliationValidator` before any of its Transactions are committed.

Per [ADR-0001](../../../docs/adr/0001-reconciliation-gate-is-mandatory-and-binary.md), the Reconciliation Gate is binary: a Statement either reconciles cleanly (`opening_balance + sum(transactions) == closing_balance` within €0.01) and commits all of its Transactions, or it commits **none**. There is no "force commit with warnings" path.

A failing Statement leaves the source PDF in the Inbox alongside a sidecar `.error.json` describing the diff (`expected_closing`, `computed`, `diff_eur`, `transactions_extracted`). The dashboard surfaces a banner showing how many Statements currently need review.

The `LLMPort` abstraction is a load-bearing seam: it is what allows the LLM runtime to be swapped (Ollama, llama.cpp, etc.) without rewriting extraction logic. The vLLM adapter is the only implementation shipped in v1 (story 35).

This slice is HITL: vLLM hardware setup, prompt design for cross-bank PDF extraction (3–5 EU banks in scope), and quality assessment of extraction results all need human judgment.

## Acceptance criteria

- [ ] `LLMPort` interface is defined and `vLLMAdapter` is the v1 implementation
- [ ] `PDFExtractor.extract(pdf_bytes) → ExtractionResult` produces correct output for at least one real bank PDF fixture per supported EU bank
- [ ] `ReconciliationValidator.validate(ExtractionResult) → Outcome` enforces `opening + sum == closing` within €0.01
- [ ] Failing Statements: PDF stays in Inbox; sidecar `.error.json` is written with the diff; zero Transactions are committed; Statement row marked `needs_review`
- [ ] Successful Statements: all Transactions committed in a single transaction; PDF moves to Processed Archive
- [ ] Dashboard shows a banner: "N statements need review" when at least one `needs_review` Statement exists
- [ ] Golden-file fixture tests for `PDFExtractor` (real PDFs from each in-scope bank, expected `ExtractionResult` checked into the repo)
- [ ] Table-driven tests for `ReconciliationValidator` covering: balanced, off-by-€0.01, off-by-cents, sign-flipped row, missing row
- [ ] Integration test for the failing path: feed a doctored ExtractionResult that doesn't reconcile; assert the sidecar appears and no Transactions are committed
- [ ] README setup section documents the vLLM hardware prerequisite (CUDA-capable GPU) and the model used in v1

## Blocked by

- Slice 02 (Folder Watcher + JSON Ingest)
