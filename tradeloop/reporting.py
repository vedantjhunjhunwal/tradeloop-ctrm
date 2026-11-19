"""A simplified, REMIT-style transaction report built from the audit log.

This is a teaching model of regulatory trade reporting, not a compliant
REMIT/ACER submission: it covers a subset of fields and checks.
"""
import csv
import hashlib
import io
import re

from .reference import COMMODITIES, COUNTERPARTIES, OUR_ENTITY

ACTION = {"CAPTURE": "N", "AMEND": "M", "CANCEL": "C"}
FIELDS = ["record_seq", "action_type", "uti", "trade_id", "version", "trade_date",
          "reporting_lei", "other_lei", "buy_sell", "commodity", "contract_type",
          "delivery_start", "delivery_end", "quantity", "unit", "price", "currency"]
LEI = re.compile(r"^[0-9A-Z]{18}[0-9A-Z]{2}$")


def uti(trade_id: str) -> str:
    """Unique transaction identifier: stable for the life of the trade."""
    return OUR_ENTITY.lei + hashlib.sha1(trade_id.encode()).hexdigest()[:20].upper()


def build(store) -> list[dict]:
    rows = []
    versions = {}
    for ev in store.audit():
        if ev["event"] not in ACTION:
            continue
        tid = ev["trade_id"]
        if tid not in versions:
            versions[tid] = {v.version: v for v in store.versions(tid)}
        t = versions[tid].get(ev["version"]) or store.get(tid)
        rows.append({
            "record_seq": len(rows) + 1, "action_type": ACTION[ev["event"]], "uti": uti(tid),
            "trade_id": tid, "version": ev["version"], "trade_date": t.trade_date,
            "reporting_lei": OUR_ENTITY.lei, "other_lei": COUNTERPARTIES[t.counterparty].lei,
            "buy_sell": "B" if t.direction == "BUY" else "S", "commodity": t.commodity,
            "contract_type": "FW" if t.product == "PHYS_FWD" else "SW",
            "delivery_start": t.delivery_start, "delivery_end": t.delivery_end,
            "quantity": t.quantity, "unit": COMMODITIES[t.commodity].unit,
            "price": t.price, "currency": COMMODITIES[t.commodity].currency})
    return rows


def check(rows: list[dict]) -> list[dict]:
    """Field-level checks a regulator's validation would apply."""
    errs = []
    seen_new = set()
    for r in rows:
        for f in FIELDS:
            if r.get(f) in (None, ""):
                errs.append({"seq": r.get("record_seq"), "rule": "RP-01", "msg": f"{f} is empty"})
        for f in ("reporting_lei", "other_lei"):
            if r.get(f) and not LEI.match(r[f]):
                errs.append({"seq": r["record_seq"], "rule": "RP-02", "msg": f"{f} {r[f]} is not a valid LEI format"})
        if r["action_type"] == "N":
            if r["uti"] in seen_new:
                errs.append({"seq": r["record_seq"], "rule": "RP-03", "msg": "duplicate NEW for same UTI"})
            seen_new.add(r["uti"])
        elif r["uti"] not in seen_new:
            errs.append({"seq": r["record_seq"], "rule": "RP-04", "msg": f"{r['action_type']} before NEW"})
        if r["quantity"] is not None and r["quantity"] <= 0:
            errs.append({"seq": r["record_seq"], "rule": "RP-05", "msg": "quantity must be positive"})
    return errs


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
