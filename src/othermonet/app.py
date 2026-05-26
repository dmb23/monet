"""FastAPI application for the expense tracker dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import inbox_dir
from .db import get_db, init_db
from .inbox import process_existing, start_watcher
from .registrations import load_registrations, reconcile_accounts_table

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    con = get_db()
    rows = con.execute(
        """SELECT t.id, t.booking_date, t.description, t.amount_cents,
                  t.kind, a.iban, a.owner
           FROM transactions t
           JOIN accounts a ON t.account_id = a.id
           ORDER BY t.booking_date DESC"""
    ).fetchall()
    con.close()

    transactions = [
        {
            "id": r[0],
            "booking_date": r[1],
            "description": r[2],
            "amount_cents": r[3],
            "amount": f"{r[3] / 100:.2f}€",
            "kind": r[4],
            "iban": r[5],
            "owner": r[6],
        }
        for r in rows
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "transactions": transactions,
            "needs_review_count": _count_needs_review(),
        },
    )


def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("othermonet.app:app", host="127.0.0.1", port=5000, reload=False)
