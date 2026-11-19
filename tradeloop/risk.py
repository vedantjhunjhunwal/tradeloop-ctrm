"""Positions, mark-to-market, daily P&L explain, historical VaR and credit
exposure against counterparty limits. All money figures are in USD."""
import math
from collections import defaultdict

from . import months
from .reference import COMMODITIES, COUNTERPARTIES, FX_TO_USD

RATE = 0.035  # flat discount rate for the demo


def _df(as_of: str, month: str) -> float:
    t = max(0, months.to_int(month) - months.to_int(months.month_of(as_of))) / 12 + 0.5 / 12
    return math.exp(-RATE * t)


def open_months(t, as_of: str) -> list[str]:
    cur = months.to_int(months.month_of(as_of))
    return [m for m in t.delivery_months() if months.to_int(m) >= cur]


def positions(trades, as_of: str) -> dict[tuple, float]:
    """Net open quantity by (book, commodity, month). Positive = long."""
    pos = defaultdict(float)
    for t in trades:
        for m in open_months(t, as_of):
            pos[(t.book, t.commodity, m)] += t.sign * t.quantity
    return {k: round(v, 6) for k, v in sorted(pos.items()) if abs(v) > 1e-9}


def trade_mtm(t, market, as_of: str, on: str | None = None) -> float:
    fx = FX_TO_USD[COMMODITIES[t.commodity].currency]
    curve = market.curve(t.commodity, on)
    return sum(t.sign * t.quantity * (curve[m] - t.price) * _df(as_of, m) * fx
               for m in open_months(t, as_of))


def mtm_by(trades, market, as_of: str, key) -> dict[str, float]:
    out = defaultdict(float)
    for t in trades:
        out[key(t)] += trade_mtm(t, market, as_of)
    return {k: round(v, 2) for k, v in sorted(out.items())}


def pnl_explain(trades, market, as_of: str) -> dict:
    """Day-on-day MtM change split into new trades and curve moves."""
    today, yday = market.dates[-1], market.previous_date()
    new = [t for t in trades if t.trade_date == as_of]
    old = [t for t in trades if t.trade_date != as_of]
    curve_move = sum(trade_mtm(t, market, as_of, today) - trade_mtm(t, market, as_of, yday) for t in old)
    new_trades = sum(trade_mtm(t, market, as_of, today) for t in new)
    total = (sum(trade_mtm(t, market, as_of, today) for t in trades)
             - sum(trade_mtm(t, market, as_of, yday) for t in old))
    return {"curve_move": round(curve_move, 2), "new_trades": round(new_trades, 2),
            "total": round(total, 2), "unexplained": round(total - curve_move - new_trades, 2)}


def historical_var(trades, market, as_of: str, window: int = 250) -> dict:
    """1-day historical-simulation VaR on delta positions."""
    pos = positions(trades, as_of)
    scen = [0.0] * window
    by_com = {c: [0.0] * window for c in COMMODITIES}
    for (book, com, m), q in pos.items():
        fx = FX_TO_USD[COMMODITIES[com].currency]
        for i, d in enumerate(market.daily_changes(com, m, window)):
            v = q * d * _df(as_of, m) * fx
            scen[i] += v
            by_com[com][i] += v

    def q(xs, p):
        s = sorted(xs)
        return round(-s[int(math.floor((1 - p) * len(s)))], 2)

    return {"window_days": window, "var95": q(scen, 0.95), "var99": q(scen, 0.99),
            "by_commodity_var95": {c: q(v, 0.95) for c, v in by_com.items()}}


def credit_exposure(trades, market, as_of: str, receivables: dict[str, float] | None = None) -> list[dict]:
    """Exposure = max(0, MtM) + unpaid receivables, checked against the limit."""
    receivables = receivables or {}
    mtm = mtm_by(trades, market, as_of, key=lambda t: t.counterparty)
    rows = []
    for code, cp in COUNTERPARTIES.items():
        if code not in mtm and code not in receivables:
            continue
        exp = max(0.0, mtm.get(code, 0.0)) + max(0.0, receivables.get(code, 0.0))
        util = exp / cp.credit_limit_usd
        rows.append({"counterparty": code, "mtm_usd": mtm.get(code, 0.0),
                     "receivable_usd": round(receivables.get(code, 0.0), 2),
                     "exposure_usd": round(exp, 2), "limit_usd": cp.credit_limit_usd,
                     "utilisation": round(util, 4),
                     "status": "BREACH" if util > 1 else ("WARN" if util > 0.8 else "OK")})
    return rows
