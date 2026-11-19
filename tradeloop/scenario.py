"""End-to-end demo scenario. Builds a seeded book of trades, pushes it through
the whole lifecycle and writes results/ with every figure the README quotes.

Run:  python -m tradeloop.scenario
"""
import copy
import csv
import dataclasses
import json
import random
import re
from pathlib import Path

from . import confirmations, months, reporting, risk, settlement
from .market import MarketData
from .reference import BOOK_FOR, COMMODITIES, COUNTERPARTIES
from .settlement import Line
from .trades import Trade, TradeStore, ValidationError

AS_OF = "2026-11-20"
QTY = {"POWER_DE": (1_000, 20_000, 500), "GAS_TTF": (5_000, 50_000, 1_000), "BRENT": (5_000, 60_000, 5_000)}


def make_trades(market, rng, n=240):
    active = [c for c, cp in COUNTERPARTIES.items() if cp.active]
    out = []
    for i in range(n):
        com = rng.choice(list(COMMODITIES))
        start = months.from_int(months.to_int("2026-06") + rng.randrange(16))
        end = min(months.add(start, rng.randrange(6)), "2027-12")
        today_trade = i >= n - 6
        if today_trade and start <= AS_OF[:7]:
            start, end = "2027-01", "2027-03"
        cands = [d for d in market.dates[-150:] if d[:7] < start]
        td = AS_OF if today_trade else rng.choice(cands or market.dates[-150:-1])
        lo, hi, step = QTY[com]
        ref = market.strip_price(com, start, end, td)
        out.append(Trade(
            trade_id=f"TL-{i + 1:06d}", trade_date=td, book=BOOK_FOR[com],
            trader=rng.choice(["asharma", "jmeyer", "lchen"]), counterparty=rng.choice(active),
            commodity=com, product="SWAP" if rng.random() < 0.3 else "PHYS_FWD",
            direction=rng.choice(["BUY", "SELL"]), quantity=float(rng.randrange(lo, hi + 1, step)),
            price=round(ref * (1 + rng.gauss(0, 0.01)), 2), delivery_start=start, delivery_end=end))
    return out


def bad_tickets(good: Trade) -> list[tuple[str, Trade]]:
    b = lambda **kw: dataclasses.replace(good, **kw)
    return [
        ("VR-01", b(trade_id="TL-900001", trader="")),
        ("VR-02", b(trade_id="TL-900002", commodity="COAL_API2")),
        ("VR-02", b(trade_id="TL-900003", product="OPTION")),
        ("VR-03", b(trade_id="TL-900004", counterparty="DORMANT")),
        ("VR-03", b(trade_id="TL-900005", counterparty="UNKNOWNCO")),
        ("VR-04", b(trade_id="TL-900006", quantity=-5000.0)),
        ("VR-04", b(trade_id="TL-900007", price=0.0)),
        ("VR-05", b(trade_id="TL-900008", delivery_start="2027-05", delivery_end="2027-02")),
        ("VR-06", b(trade_id="TL-900009", trade_date="2026-12-15")),
        ("VR-07", b(trade_id="TL-900010", price=round(good.price * 1.6, 2))),
        ("VR-07", b(trade_id="TL-900011", price=round(good.price * 0.5, 2))),
        ("VR-01", b(trade_id=good.trade_id)),  # duplicate id
    ]


def run(out_dir: str = "results", seed: int = 11) -> dict:
    rng = random.Random(seed)
    market = MarketData(AS_OF)
    store = TradeStore(as_of=AS_OF, market=market)
    summary = {"as_of": AS_OF}

    # 1. Capture -------------------------------------------------------------
    trades = make_trades(market, rng)
    for t in trades:
        store.capture(t, user=t.trader)
    rejected = []
    for rule, t in bad_tickets(trades[0]):
        try:
            store.capture(t, user="uat")
            rejected.append({"expected": rule, "got": "ACCEPTED"})
        except ValidationError as e:
            rejected.append({"expected": rule, "got": e.failures[0][0], "msg": e.failures[0][1]})
    summary["capture"] = {"captured": len(trades),
                          "bad_tickets": len(rejected),
                          "bad_tickets_rejected_by_expected_rule": sum(r["expected"] == r["got"] for r in rejected),
                          "price_warnings": sum(bool(t.warnings) for t in store.all())}

    # 2. Amend and cancel ----------------------------------------------------
    ids = [t.trade_id for t in trades[:-6]]
    amended = rng.sample(ids, 15)
    for tid in amended:
        t = store.get(tid)
        ch = {"quantity": t.quantity + QTY[t.commodity][2]} if rng.random() < 0.5 else {"price": round(t.price + 0.25, 2)}
        store.amend(tid, ch, user="ops")
    cancelled = rng.sample([i for i in ids if i not in amended], 8)
    for tid in cancelled:
        store.cancel(tid, user="ops", reason="booked in error")
    summary["lifecycle"] = {"amended": len(amended), "cancelled": len(cancelled)}

    # 3. Confirmation matching ----------------------------------------------
    live = store.all()
    truth, results = {}, {}
    for t in live:
        kind = rng.random()
        ov, expect = {}, ("MATCHED", [])
        if kind < 0.04:
            ov, expect = {"price": round(t.price + 0.50, 2)}, ("MISMATCH", ["price"])
        elif kind < 0.08:
            ov, expect = {"quantity": t.quantity + QTY[t.commodity][2]}, ("MISMATCH", ["quantity"])
        elif kind < 0.10:
            ov, expect = {"delivery_end": months.add(t.delivery_end, 1)}, ("MISMATCH", ["delivery_end"])
        elif kind < 0.12:
            ov, expect = {"direction": "SELL" if t.direction == "BUY" else "BUY"}, ("MISMATCH", ["direction"])
        doc = confirmations.render(t, rng.randrange(3), ov, cpty_ref=f"CF{rng.randrange(10**6):06d}")
        if 0.12 <= kind < 0.14:  # scanned badly: price line lost
            doc = re.sub(r"(EUR|USD) [\d,]+\.\d+", r"\1 [illegible]", doc)
            expect = ("UNREADABLE", ["price"])
        truth[t.trade_id] = expect
        e = confirmations.parse(doc)
        target = store.get(e.our_ref) if e.our_ref else t
        results[t.trade_id] = confirmations.match(e, target)
        if results[t.trade_id]["status"] == "MATCHED":
            store.confirm(t.trade_id, user="confirmations", ref="auto")
    correct = sum(results[k]["status"] == v[0] and sorted(results[k]["fields"]) == sorted(v[1])
                  for k, v in truth.items())
    exc = [{"trade_id": k, **r} for k, r in results.items() if r["status"] != "MATCHED"]
    summary["confirmations"] = {
        "documents": len(truth), "templates": 3,
        "auto_matched": sum(r["status"] == "MATCHED" for r in results.values()),
        "exceptions": len(exc),
        "injected_errors": sum(v[0] != "MATCHED" for v in truth.values()),
        "classified_correctly": correct,
        "false_matches": sum(results[k]["status"] == "MATCHED" and v[0] != "MATCHED" for k, v in truth.items())}

    # 4. Settlement and reconciliation --------------------------------------
    live = store.all()
    ours = settlement.invoice_lines(live, market, AS_OF)
    theirs, injected = [], []
    for ln in ours:
        r = rng.random()
        c = copy.deepcopy(ln)
        if r < 0.03:
            c.amount = round(c.amount + rng.choice([-1, 1]) * rng.choice([125.0, 980.5, 2400.0]), 2)
            injected.append(("AMOUNT", ln.trade_id, ln.month))
        elif r < 0.05:
            c.quantity += 500
            injected.append(("QUANTITY", ln.trade_id, ln.month))
        elif r < 0.07:
            injected.append(("MISSING_AT_CPTY", ln.trade_id, ln.month))
            continue
        elif r < 0.085:
            theirs.append(copy.deepcopy(c))
            injected.append(("DUPLICATE", ln.trade_id, ln.month))
        theirs.append(c)
    for k in range(4):
        theirs.append(Line(f"TL-{800000 + k:06d}", "2026-10", "NORDVIK", "PHYSICAL", 1000.0, 80.0, -80000.0, "EUR"))
        injected.append(("MISSING_IN_OURS", f"TL-{800000 + k:06d}", "2026-10"))
    rec = settlement.reconcile(ours, theirs)
    found = {(b["type"], b["trade_id"], b["month"]) for b in rec["breaks"]}
    inj = set(injected)
    summary["reconciliation"] = {
        "our_lines": rec["our_lines"], "their_lines": rec["their_lines"], "matched": rec["matched"],
        "breaks_found": len(rec["breaks"]), "breaks_injected": len(inj),
        "injected_found_with_right_type": len(inj & found), "false_breaks": len(found - inj),
        "by_type": rec["summary"]}

    settled = 0
    for t in store.all():
        if t.status == "CONFIRMED" and months.to_int(t.delivery_end) < months.to_int(AS_OF[:7]):
            store.settle(t.trade_id, user="settlements")
            settled += 1
    summary["lifecycle"]["settled"] = settled
    summary["lifecycle"]["status_counts"] = {
        s: sum(t.status == s for t in store.all(include_cancelled=True))
        for s in ("VALIDATED", "CONFIRMED", "SETTLED", "CANCELLED")}

    # 5. Risk ----------------------------------------------------------------
    live = store.all()
    pos = risk.positions(live, AS_OF)
    recv = settlement.receivables_usd(ours, months.add(AS_OF[:7], -1))
    exposure = risk.credit_exposure(live, market, AS_OF, recv)
    var = risk.historical_var(live, market, AS_OF)
    pnl = risk.pnl_explain(live, market, AS_OF)
    summary["risk"] = {
        "open_position_buckets": len(pos),
        "mtm_by_book_usd": risk.mtm_by(live, market, AS_OF, key=lambda t: t.book),
        "var": var, "pnl_explain_usd": pnl,
        "credit": {s: sum(r["status"] == s for r in exposure) for s in ("OK", "WARN", "BREACH")}}

    # 6. Regulatory report ---------------------------------------------------
    rows = reporting.build(store)
    errs = reporting.check(rows)
    summary["reporting"] = {"records": len(rows),
                            "by_action": {a: sum(r["action_type"] == a for r in rows) for a in "NMC"},
                            "validation_errors": len(errs)}
    summary["audit_events"] = len(store.audit())

    # 7. Write outputs -------------------------------------------------------
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _csv(out / "confirmation_exceptions.csv",
         [{"trade_id": e["trade_id"], "status": e["status"], "fields": "|".join(e["fields"])} for e in exc])
    _csv(out / "recon_breaks.csv", rec["breaks"])
    _csv(out / "credit_exposure.csv", exposure)
    _csv(out / "positions.csv", [{"book": b, "commodity": c, "month": m, "net_qty": q} for (b, c, m), q in pos.items()])
    (out / "remit_report.csv").write_text(reporting.to_csv(rows))
    return summary


def _csv(path, rows):
    with open(path, "w", newline="") as f:
        if not rows:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
