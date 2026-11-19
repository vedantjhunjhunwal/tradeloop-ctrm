"""Settlement: invoice lines for delivered months, counterparty netting and
reconciliation of our lines against the counterparty's statement.

Amounts are signed from our side: positive = we receive, negative = we pay.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from . import months
from .reference import COMMODITIES, FX_TO_USD


@dataclass
class Line:
    trade_id: str
    month: str
    counterparty: str
    kind: str          # PHYSICAL | FINANCIAL
    quantity: float
    price: float       # fixed price (physical) or index fixing (financial)
    amount: float
    currency: str


def delivered_months(t, as_of: str) -> list[str]:
    cur = months.to_int(months.month_of(as_of))
    return [m for m in t.delivery_months() if months.to_int(m) < cur]


def invoice_lines(trades, market, as_of: str) -> list[Line]:
    out = []
    for t in trades:
        for m in delivered_months(t, as_of):
            if t.product == "PHYS_FWD":
                amt = -t.sign * t.quantity * t.price
                out.append(Line(t.trade_id, m, t.counterparty, "PHYSICAL", t.quantity, t.price,
                                round(amt, 2), t.currency))
            else:
                fix = market.fixing(t.commodity, m)
                amt = t.sign * t.quantity * (fix - t.price)
                out.append(Line(t.trade_id, m, t.counterparty, "FINANCIAL", t.quantity, fix,
                                round(amt, 2), t.currency))
    return out


def netting(lines: list[Line]) -> dict[tuple, float]:
    """Net amount per (counterparty, month, currency)."""
    net = defaultdict(float)
    for ln in lines:
        net[(ln.counterparty, ln.month, ln.currency)] += ln.amount
    return {k: round(v, 2) for k, v in sorted(net.items())}


def receivables_usd(lines: list[Line], unpaid_month: str) -> dict[str, float]:
    """Net receivable per counterparty for the month not yet paid."""
    out = defaultdict(float)
    for (cp, m, ccy), v in netting(lines).items():
        if m == unpaid_month:
            out[cp] += v * FX_TO_USD[ccy]
    return dict(out)


BREAK_TYPES = ("MISSING_AT_CPTY", "MISSING_IN_OURS", "DUPLICATE", "QUANTITY", "AMOUNT")


def reconcile(ours: list[Line], theirs: list[Line], tol: float = 0.01) -> dict:
    """Match on (trade_id, month); classify every difference."""
    key = lambda ln: (ln.trade_id, ln.month)
    counts = Counter(key(ln) for ln in theirs)
    theirs_by = {}
    breaks = []
    for ln in theirs:
        k = key(ln)
        if k in theirs_by:
            continue
        theirs_by[k] = ln
        if counts[k] > 1:
            breaks.append({"type": "DUPLICATE", "trade_id": k[0], "month": k[1],
                           "detail": f"{counts[k]} lines on counterparty statement"})
    ours_by = {key(ln): ln for ln in ours}
    matched = 0
    for k, o in ours_by.items():
        c = theirs_by.get(k)
        if c is None:
            breaks.append({"type": "MISSING_AT_CPTY", "trade_id": k[0], "month": k[1],
                           "detail": f"our amount {o.amount} {o.currency}"})
        elif abs(o.quantity - c.quantity) > 1e-6:
            breaks.append({"type": "QUANTITY", "trade_id": k[0], "month": k[1],
                           "detail": f"ours {o.quantity} vs theirs {c.quantity}"})
        elif abs(o.amount - c.amount) > tol:
            breaks.append({"type": "AMOUNT", "trade_id": k[0], "month": k[1],
                           "detail": f"ours {o.amount} vs theirs {c.amount} "
                                     f"(diff {round(c.amount - o.amount, 2)})"})
        else:
            matched += 1
    for k in theirs_by.keys() - ours_by.keys():
        breaks.append({"type": "MISSING_IN_OURS", "trade_id": k[0], "month": k[1],
                       "detail": f"their amount {theirs_by[k].amount}"})
    summary = Counter(b["type"] for b in breaks)
    return {"our_lines": len(ours), "their_lines": len(theirs), "matched": matched,
            "breaks": sorted(breaks, key=lambda b: (b["type"], b["trade_id"], b["month"])),
            "summary": {t: summary.get(t, 0) for t in BREAK_TYPES}}


def to_rows(lines: list[Line]) -> list[dict]:
    return [asdict(ln) for ln in lines]
