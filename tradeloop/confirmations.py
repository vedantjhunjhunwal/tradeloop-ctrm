"""Confirmation matching: read counterparty trade confirmations (free-text
emails in a few different layouts), pull out the economic fields and compare
them with the captured trade. Rule-based, so every extraction is explainable.
"""
import re
from dataclasses import dataclass, field

from .reference import COMMODITIES, COUNTERPARTIES, OUR_ENTITY

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
COMMODITY_WORDS = [
    ("POWER_DE", r"power|baseload|electricity"),
    ("GAS_TTF", r"\bttf\b|natural gas|\bgas\b"),
    ("BRENT", r"brent|crude"),
]
NAME_TO_CP = {cp.name.lower(): code for code, cp in COUNTERPARTIES.items()}


@dataclass
class Extracted:
    our_ref: str | None = None
    counterparty: str | None = None
    direction: str | None = None      # from OUR side
    commodity: str | None = None
    product: str | None = None
    delivery_start: str | None = None
    delivery_end: str | None = None
    quantity: float | None = None
    price: float | None = None
    missing: list = field(default_factory=list)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _month(tok: str) -> str | None:
    tok = tok.strip().lower()
    m = re.match(r"([a-z]{3})[a-z]*[-\s']*(\d{2,4})", tok)
    if m and m.group(1) in MONTHS:
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{MONTHS[m.group(1)]:02d}"
    m = re.match(r"(\d{4})-(\d{2})", tok)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def parse(text: str) -> Extracted:
    low = text.lower()
    e = Extracted()
    m = re.search(r"(?:our ref(?:erence)?|your ref(?:erence)?|ref(?:erence)? no\.?)\s*[:#]?\s*(TL-\d+)", text, re.I)
    e.our_ref = m.group(1).upper() if m else (re.search(r"\b(TL-\d{6})\b", text) or [None, None])[1]

    for name, code in NAME_TO_CP.items():
        if name in low:
            e.counterparty = code
            break
    # Direction: who is the buyer?
    ours = OUR_ENTITY.name.lower()
    mb = re.search(r"buyer\s*[:\-]\s*([^\n;]+)", low)
    ms = re.search(r"seller\s*[:\-]\s*([^\n;]+)", low)
    if mb:
        e.direction = "BUY" if ours in mb.group(1) else "SELL"
    elif ms:
        e.direction = "SELL" if ours in ms.group(1) else "BUY"
    else:
        m = re.search(r"(\w[\w\s]*?)\s+(buys|sells|bought|sold)\s+", low)
        if m:
            subj_is_us = ours.split()[0] in m.group(1)
            buys = m.group(2) in ("buys", "bought")
            e.direction = "BUY" if buys == subj_is_us else "SELL"

    # Company names can contain commodity words ("Thames Gas Trading"), so drop them first.
    body = low
    for name in list(NAME_TO_CP) + [ours]:
        body = body.replace(name, " ")
    for code, pat in COMMODITY_WORDS:
        if re.search(pat, body):
            e.commodity = code
            break
    if re.search(r"swap|financial|cash[-\s]settled|fixed[-\s]for[-\s]float", low):
        e.product = "SWAP"
    elif re.search(r"physical|forward|delivery point|delivered", low):
        e.product = "PHYS_FWD"

    m = re.search(r"(?:delivery|period|pricing period|tenor)[^:\n]*[:\-]?\s*"
                  r"([A-Za-z]{3,9}[-\s']*\d{2,4}|\d{4}-\d{2})\s*(?:to|-|–|through|until)\s*"
                  r"([A-Za-z]{3,9}[-\s']*\d{2,4}|\d{4}-\d{2})", text, re.I)
    if m:
        e.delivery_start, e.delivery_end = _month(m.group(1)), _month(m.group(2))
    else:
        m = re.search(r"(?:delivery|period|month)[^:\n]*[:\-]\s*([A-Za-z]{3,9}[-\s']*\d{2,4}|\d{4}-\d{2})\b", text, re.I)
        if m:
            e.delivery_start = e.delivery_end = _month(m.group(1))

    m = re.search(r"(?:quantity|volume|qty)\s*[:\-]?\s*([\d,]+(?:\.\d+)?)\s*(mwh|bbl|barrels)", low) or \
        re.search(r"([\d,]+(?:\.\d+)?)\s*(mwh|bbl|barrels)\s*(?:per|/|a)\s*month", low)
    if m:
        e.quantity = _num(m.group(1))
    m = re.search(r"(?:price|fixed price|at)\s*[:\-]?\s*(?:eur|usd|€|\$)\s*([\d,]+\.\d+|[\d,]+)", low) or \
        re.search(r"([\d,]+\.\d+)\s*(?:eur|usd)\s*/\s*(?:mwh|bbl)", low)
    if m:
        e.price = _num(m.group(1))
    e.missing = [f for f in ("our_ref", "counterparty", "direction", "commodity", "product",
                             "delivery_start", "delivery_end", "quantity", "price")
                 if getattr(e, f) is None]
    return e


FIELDS = ("counterparty", "direction", "commodity", "product", "delivery_start",
          "delivery_end", "quantity", "price")


def match(e: Extracted, trade, price_tol: float = 0.005) -> dict:
    """Compare extracted fields to the trade. Returns MATCHED, MISMATCH or
    UNREADABLE (fields that could not be read go to manual review)."""
    if e.missing:
        return {"status": "UNREADABLE", "fields": e.missing}
    diffs = []
    for f in FIELDS:
        a, b = getattr(e, f), getattr(trade, f)
        if f == "price":
            if abs(a - b) > price_tol:
                diffs.append((f, b, a))
        elif f == "quantity":
            if abs(a - b) > 1e-6:
                diffs.append((f, b, a))
        elif a != b:
            diffs.append((f, b, a))
    if diffs:
        return {"status": "MISMATCH", "fields": [d[0] for d in diffs],
                "detail": [{"field": f, "ours": o, "theirs": t} for f, o, t in diffs]}
    return {"status": "MATCHED", "fields": []}


def render(trade, template: int, overrides: dict | None = None, cpty_ref: str = "") -> str:
    """Write a confirmation the way a counterparty might send it. Used by the
    demo scenario to create test documents; overrides inject errors."""
    v = {f: getattr(trade, f) for f in FIELDS}
    v.update(overrides or {})
    cp = COUNTERPARTIES[v["counterparty"]].name
    com = COMMODITIES[v["commodity"]]
    buyer, seller = (OUR_ENTITY.name, cp) if v["direction"] == "BUY" else (cp, OUR_ENTITY.name)
    mon = lambda m: f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m[5:])-1]}-{m[:4]}"
    prod = "Fixed-for-Floating Swap (cash settled)" if v["product"] == "SWAP" else "Physical Forward"
    q = f"{v['quantity']:,.0f}"
    if template == 0:
        return (f"TRADE CONFIRMATION\nConfirmation No: {cpty_ref}\nOur Ref: {trade.trade_id}\n"
                f"Trade Date: {trade.trade_date}\nSeller: {seller}\nBuyer: {buyer}\n"
                f"Product: {com.name} {prod}\nDelivery Period: {mon(v['delivery_start'])} to "
                f"{mon(v['delivery_end'])}\nQuantity: {q} {com.unit} per month\n"
                f"Price: {com.currency} {v['price']:.2f}/{com.unit}\n")
    if template == 1:
        verb = "buys" if buyer == cp else "sells"
        return (f"Dear Sirs,\n\nWe confirm that {cp} {verb} from/to {OUR_ENTITY.name} "
                f"{q} {com.unit} per month of {com.name}, {prod.lower()}, for the period "
                f"{mon(v['delivery_start'])} to {mon(v['delivery_end'])} at {com.currency} "
                f"{v['price']:.2f} per {com.unit}.\nYour reference: {trade.trade_id}. "
                f"Our reference: {cpty_ref}.\n\nKind regards,\nConfirmations Desk")
    return (f"{cp} | Deal Ticket {cpty_ref}\n"
            f"Ref No. {trade.trade_id}; Buyer - {buyer}; Seller - {seller}\n"
            f"Commodity - {com.name} ({prod})\n"
            f"Tenor - {v['delivery_start']} through {v['delivery_end']}\n"
            f"Volume - {q} {com.unit} / month; Fixed Price - {com.currency} {v['price']:.2f}\n")
