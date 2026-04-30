"""FastAPI application for the expense tracker dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import get_db, init_db
from .inbox import start_watcher
from .seed import seed_if_empty

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_if_empty()
    observer = start_watcher()
    try:
        yield
    finally:
        observer.stop()
        observer.join()


app = FastAPI(title="Othermonet", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Render the dashboard page listing all Transactions."""
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
        request, "dashboard.html", {"transactions": transactions}
    )


def main():
    """Run the FastAPI app via uvicorn (DB init + watcher start happen in lifespan)."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("othermonet.app:app", host="127.0.0.1", port=5000, reload=False)
