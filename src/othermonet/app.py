"""FastAPI application for the expense tracker dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import inbox_dir
from .db import get_db, init_db
from .inbox import process_existing, start_watcher
from .registrations import load_registrations, reconcile_accounts_table
from .seed import UNCATEGORIZED, seed_categories

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_categories()
    registrations = load_registrations()
    reconcile_accounts_table(registrations)
    process_existing(registrations)
    observer = start_watcher(registrations)
    try:
        yield
    finally:
        observer.stop()
        observer.join()


app = FastAPI(title="Othermonet", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")


def _count_needs_review() -> int:
    """`statements.status = 'needs_review'` rows plus stranded `.error.json` sidecars."""
    con = get_db()
    try:
        statement_count = con.execute(
            "SELECT COUNT(*) FROM statements WHERE status = 'needs_review'"
        ).fetchone()[0]
    finally:
        con.close()
    sidecar_count = sum(1 for _ in inbox_dir().glob("*.error.json"))
    return statement_count + sidecar_count


KIND_CHOICES = ("Expense", "Income", "Transfer")


def _load_transactions() -> list[dict]:
    con = get_db()
    try:
        rows = con.execute(
            """SELECT t.id, t.booking_date, t.description, t.amount_cents,
                      t.kind, a.iban, a.owner, t.value_date,
                      t.counterparty_iban, t.counterparty_name,
                      t.category_id
               FROM transactions t
               JOIN accounts a ON t.account_id = a.id
               ORDER BY t.booking_date DESC"""
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": r[0],
            "booking_date": r[1],
            "description": r[2],
            "amount_cents": r[3],
            "amount": f"{r[3] / 100:.2f}€",
            "kind": r[4],
            "iban": r[5],
            "owner": r[6],
            "value_date": r[7],
            "counterparty_iban": r[8],
            "counterparty_name": r[9],
            "category_id": r[10],
        }
        for r in rows
    ]


def _load_categories() -> list[dict]:
    con = get_db()
    try:
        rows = con.execute(
            """SELECT id, name FROM categories
               ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name""",
            [UNCATEGORIZED],
        ).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "name": r[1]} for r in rows]


def _totals(transactions: list[dict]) -> dict:
    """Spend and income totals exclude Transfer rows (issue 06 AC)."""
    income_cents = sum(
        t["amount_cents"] for t in transactions if t["kind"] == "Income"
    )
    spend_cents = sum(
        -t["amount_cents"] for t in transactions if t["kind"] == "Expense"
    )
    return {
        "income": f"{income_cents / 100:.2f}€",
        "spend": f"{spend_cents / 100:.2f}€",
        "net": f"{(income_cents - spend_cents) / 100:.2f}€",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    transactions = _load_transactions()
    categories = _load_categories()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "transactions": transactions,
            "needs_review_count": _count_needs_review(),
            "totals": _totals(transactions),
            "kind_choices": KIND_CHOICES,
            "categories": categories,
        },
    )


def _render_row(request: Request, txn_id: int) -> HTMLResponse:
    transactions = _load_transactions()
    txn = next((t for t in transactions if t["id"] == txn_id), None)
    if txn is None:
        raise HTTPException(404, f"transaction {txn_id} not found")
    return templates.TemplateResponse(
        request,
        "_row.html",
        {
            "txn": txn,
            "kind_choices": KIND_CHOICES,
            "categories": _load_categories(),
        },
    )


@app.post("/transactions/{txn_id}/kind", response_class=HTMLResponse)
def update_kind(request: Request, txn_id: int, kind: str = Form(...)):
    if kind not in KIND_CHOICES:
        raise HTTPException(400, f"invalid kind: {kind!r}")
    con = get_db()
    try:
        updated = con.execute(
            "UPDATE transactions SET kind = ? WHERE id = ? RETURNING id",
            [kind, txn_id],
        ).fetchone()
    finally:
        con.close()
    if updated is None:
        raise HTTPException(404, f"transaction {txn_id} not found")
    return _render_row(request, txn_id)


@app.post("/transactions/{txn_id}/category", response_class=HTMLResponse)
def update_category(request: Request, txn_id: int, category_id: str = Form(...)):
    # An empty string clears the assignment back to NULL (UI's "—" choice).
    cat_id: int | None = int(category_id) if category_id else None
    con = get_db()
    try:
        if cat_id is not None:
            exists = con.execute(
                "SELECT 1 FROM categories WHERE id = ?", [cat_id]
            ).fetchone()
            if exists is None:
                raise HTTPException(400, f"unknown category_id {cat_id}")
        updated = con.execute(
            "UPDATE transactions SET category_id = ? WHERE id = ? RETURNING id",
            [cat_id, txn_id],
        ).fetchone()
    finally:
        con.close()
    if updated is None:
        raise HTTPException(404, f"transaction {txn_id} not found")
    return _render_row(request, txn_id)


# --- Category CRUD ----------------------------------------------------------


@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request):
    return templates.TemplateResponse(
        request,
        "categories.html",
        {"categories": _load_categories(), "uncategorized": UNCATEGORIZED},
    )


@app.post("/categories", response_class=HTMLResponse)
def create_category(request: Request, name: str = Form(...)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "name required")
    con = get_db()
    try:
        existing = con.execute(
            "SELECT 1 FROM categories WHERE name = ?", [name]
        ).fetchone()
        if existing is not None:
            raise HTTPException(409, f"category {name!r} already exists")
        con.execute("INSERT INTO categories (name) VALUES (?)", [name])
    finally:
        con.close()
    return templates.TemplateResponse(
        request,
        "_categories_list.html",
        {"categories": _load_categories(), "uncategorized": UNCATEGORIZED},
    )


@app.post("/categories/{category_id}/rename", response_class=HTMLResponse)
def rename_category(request: Request, category_id: int, name: str = Form(...)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "name required")
    con = get_db()
    try:
        row = con.execute(
            "SELECT name FROM categories WHERE id = ?", [category_id]
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"category {category_id} not found")
        if row[0] == UNCATEGORIZED:
            raise HTTPException(400, "Uncategorized cannot be renamed")
        clash = con.execute(
            "SELECT 1 FROM categories WHERE name = ? AND id <> ?",
            [name, category_id],
        ).fetchone()
        if clash is not None:
            raise HTTPException(409, f"category {name!r} already exists")
        con.execute(
            "UPDATE categories SET name = ? WHERE id = ?", [name, category_id]
        )
    finally:
        con.close()
    return templates.TemplateResponse(
        request,
        "_categories_list.html",
        {"categories": _load_categories(), "uncategorized": UNCATEGORIZED},
    )


@app.post("/categories/{category_id}/delete", response_class=HTMLResponse)
def delete_category(request: Request, category_id: int):
    con = get_db()
    try:
        row = con.execute(
            "SELECT name FROM categories WHERE id = ?", [category_id]
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"category {category_id} not found")
        if row[0] == UNCATEGORIZED:
            raise HTTPException(400, "Uncategorized cannot be deleted")
        # Detach any transactions pointing here so the FK doesn't block delete.
        con.execute(
            "UPDATE transactions SET category_id = NULL WHERE category_id = ?",
            [category_id],
        )
        con.execute("DELETE FROM categories WHERE id = ?", [category_id])
    finally:
        con.close()
    return templates.TemplateResponse(
        request,
        "_categories_list.html",
        {"categories": _load_categories(), "uncategorized": UNCATEGORIZED},
    )


def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("othermonet.app:app", host="127.0.0.1", port=5000, reload=False)
