"""REST API over the trade store.

Run:  uvicorn tradeloop.api:app --reload   (then open /docs)
"""
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import confirmations, months, reporting, risk, settlement
from .market import MarketData
from .trades import LifecycleError, Trade, TradeStore, ValidationError

AS_OF = "2026-11-20"


class TradeIn(BaseModel):
    trade_id: str
    trade_date: str
    book: str
    trader: str
    counterparty: str
    commodity: str
    product: str
    direction: str
    quantity: float
    price: float
    delivery_start: str
    delivery_end: str


class Amend(BaseModel):
    changes: dict
    user: str = "api"


class ConfirmationDoc(BaseModel):
    text: str


def create_app(store: TradeStore | None = None, market: MarketData | None = None) -> FastAPI:
    market = market or MarketData(AS_OF)
    store = store or TradeStore(as_of=AS_OF, market=market)
    app = FastAPI(title="TradeLoop", version="1.0",
                  description="Commodity trade lifecycle: capture, confirm, risk, settle, report.")

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except ValidationError as e:
            raise HTTPException(422, [{"rule": r, "message": m} for r, m in e.failures])
        except LifecycleError as e:
            raise HTTPException(409, str(e))
        except KeyError as e:
            raise HTTPException(404, f"trade {e.args[0]} not found")

    @app.post("/trades", status_code=201)
    def capture(t: TradeIn):
        return asdict(guard(store.capture, Trade(**t.model_dump()), user=t.trader))

    @app.get("/trades/{trade_id}")
    def get(trade_id: str):
        return asdict(guard(store.get, trade_id))

    @app.get("/trades/{trade_id}/audit")
    def audit(trade_id: str):
        guard(store.get, trade_id)
        return store.audit(trade_id)

    @app.patch("/trades/{trade_id}")
    def amend(trade_id: str, body: Amend):
        return asdict(guard(store.amend, trade_id, body.changes, user=body.user))

    @app.post("/trades/{trade_id}/cancel")
    def cancel(trade_id: str):
        return asdict(guard(store.cancel, trade_id, user="api"))

    @app.post("/confirmations")
    def confirm(doc: ConfirmationDoc):
        e = confirmations.parse(doc.text)
        if not e.our_ref:
            return {"status": "UNREADABLE", "fields": ["our_ref"]}
        t = guard(store.get, e.our_ref)
        res = confirmations.match(e, t)
        if res["status"] == "MATCHED" and t.status == "VALIDATED":
            store.confirm(t.trade_id, user="confirmations", ref="api")
        return {"trade_id": t.trade_id, **res}

    @app.get("/positions")
    def positions():
        return [{"book": b, "commodity": c, "month": m, "net_qty": q}
                for (b, c, m), q in risk.positions(store.all(), AS_OF).items()]

    @app.get("/risk/mtm")
    def mtm():
        return risk.mtm_by(store.all(), market, AS_OF, key=lambda t: t.book)

    @app.get("/risk/var")
    def var():
        return risk.historical_var(store.all(), market, AS_OF)

    @app.get("/risk/credit")
    def credit():
        lines = settlement.invoice_lines(store.all(), market, AS_OF)
        recv = settlement.receivables_usd(lines, months.add(AS_OF[:7], -1))
        return risk.credit_exposure(store.all(), market, AS_OF, recv)

    @app.get("/settlement/invoices")
    def invoices():
        return settlement.to_rows(settlement.invoice_lines(store.all(), market, AS_OF))

    @app.get("/reports/transactions")
    def report():
        rows = reporting.build(store)
        return {"records": rows, "errors": reporting.check(rows)}

    return app


app = create_app()
