"""User acceptance test (UAT) runner.

Each case is written the way a business user would sign it off: a requirement
ID, the steps, and the expected result. Results go to results/uat_results.md.

Run:  python scripts/run_uat.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeloop import confirmations as C, months, reporting, risk, settlement as S  # noqa: E402
from tradeloop.market import MarketData  # noqa: E402
from tradeloop.trades import LifecycleError, Trade, TradeStore, ValidationError  # noqa: E402

AS_OF = "2026-11-20"
M = MarketData(AS_OF)
CASES = []


def case(uid, req, title, expected):
    def deco(fn):
        CASES.append((uid, req, title, expected, fn))
        return fn
    return deco


def ticket(**kw):
    base = dict(trade_id="TL-100001", trade_date="2026-10-01", book="EU_POWER", trader="uat",
                counterparty="ALPSTROM", commodity="POWER_DE", product="PHYS_FWD", direction="BUY",
                quantity=5_000.0, price=0.0, delivery_start="2027-01", delivery_end="2027-03")
    base.update(kw)
    if not base["price"]:
        base["price"] = round(M.strip_price(base["commodity"], base["delivery_start"], base["delivery_end"],
                                            base["trade_date"]), 2)
    return Trade(**base)


def fresh():
    return TradeStore(as_of=AS_OF, market=M)


def rejected_with(rule, t):
    try:
        fresh().capture(t)
    except ValidationError as e:
        assert e.failures[0][0] == rule, e.failures
        return
    raise AssertionError("ticket was accepted")


@case("UAT-01", "FR-01", "Capture a valid power forward", "Trade stored as VALIDATED, version 1")
def _():
    t = fresh().capture(ticket())
    assert (t.status, t.version) == ("VALIDATED", 1)


@case("UAT-02", "FR-01", "Ticket with no trader", "Rejected by VR-01")
def _(): rejected_with("VR-01", ticket(trader=""))


@case("UAT-03", "FR-01", "Ticket against an inactive counterparty", "Rejected by VR-03")
def _(): rejected_with("VR-03", ticket(counterparty="DORMANT"))


@case("UAT-04", "FR-02", "Delivery end before start", "Rejected by VR-05")
def _(): rejected_with("VR-05", ticket(delivery_start="2027-03", delivery_end="2027-01", price=80.0))


@case("UAT-05", "FR-02", "Trade date in the future", "Rejected by VR-06")
def _(): rejected_with("VR-06", ticket(trade_date="2026-12-01", price=80.0))


@case("UAT-06", "FR-03", "Price keyed 60% above the strip curve", "Rejected by VR-07 (fat finger)")
def _():
    t = ticket()
    rejected_with("VR-07", ticket(price=round(t.price * 1.6, 2)))


@case("UAT-07", "FR-03", "Price 20% above the strip curve", "Accepted with a VR-07 warning")
def _():
    t = fresh().capture(ticket(price=round(ticket().price * 1.2, 2)))
    assert t.warnings


@case("UAT-08", "FR-04", "Amend quantity on a confirmed trade", "Version 2, back to VALIDATED, v1 kept")
def _():
    s = fresh(); s.capture(ticket()); s.confirm("TL-100001")
    t = s.amend("TL-100001", {"quantity": 6_000.0}, user="ops")
    assert (t.version, t.status) == (2, "VALIDATED") and len(s.versions("TL-100001")) == 2


@case("UAT-09", "FR-05", "Cancel a trade, then try to confirm it", "Cancel succeeds; confirm is blocked")
def _():
    s = fresh(); s.capture(ticket()); s.cancel("TL-100001", reason="duplicate")
    try:
        s.confirm("TL-100001")
    except LifecycleError:
        return
    raise AssertionError("confirm allowed on cancelled trade")


@case("UAT-10", "FR-05", "Cancelled trade leaves positions", "No open position remains")
def _():
    s = fresh(); s.capture(ticket()); s.cancel("TL-100001")
    assert risk.positions(s.all(), AS_OF) == {}


@case("UAT-11", "FR-06", "Audit trail after capture, confirm, amend", "3 events with user and before/after values")
def _():
    s = fresh(); s.capture(ticket(), user="trader1"); s.confirm("TL-100001", user="ops1")
    s.amend("TL-100001", {"price": 90.0}, user="ops2")
    a = s.audit("TL-100001")
    assert [(x["event"], x["user"]) for x in a] == [("CAPTURE", "trader1"), ("CONFIRM", "ops1"), ("AMEND", "ops2")]
    assert "90.0" in a[-1]["detail"]


@case("UAT-12", "FR-07", "Matching confirmation in each of the 3 layouts", "Auto-confirmed")
def _():
    for tpl in range(3):
        s = fresh(); t = s.capture(ticket())
        assert C.match(C.parse(C.render(t, tpl, cpty_ref="X")), t)["status"] == "MATCHED"


@case("UAT-13", "FR-07", "Counterparty confirms a different price", "MISMATCH on price; trade stays VALIDATED")
def _():
    t = ticket()
    r = C.match(C.parse(C.render(t, 0, {"price": t.price + 0.5})), t)
    assert r["status"] == "MISMATCH" and r["fields"] == ["price"]


@case("UAT-14", "FR-07", "Confirmation with the price smudged", "UNREADABLE, routed to manual review")
def _():
    t = ticket()
    doc = C.render(t, 1).replace(f"{t.price:.2f}", "[illegible]")
    assert C.match(C.parse(doc), t)["status"] == "UNREADABLE"


@case("UAT-15", "FR-08", "Long 5,000 and short 2,000 in the same month", "Net position +3,000")
def _():
    ts = [ticket(), ticket(trade_id="TL-100002", direction="SELL", quantity=2_000.0)]
    assert risk.positions(ts, AS_OF)[("EU_POWER", "POWER_DE", "2027-01")] == 3_000


@case("UAT-16", "FR-09", "Daily P&L explain", "Curve move + new trades = total, nothing unexplained")
def _():
    ts = [ticket(), ticket(trade_id="TL-100002", trade_date=AS_OF, direction="SELL")]
    p = risk.pnl_explain(ts, M, AS_OF)
    assert abs(p["unexplained"]) < 0.01


@case("UAT-17", "FR-10", "VaR on an offsetting buy and sell", "VaR is zero")
def _():
    ts = [ticket(), ticket(trade_id="TL-100002", direction="SELL")]
    assert risk.historical_var(ts, M, AS_OF)["var95"] == 0


@case("UAT-18", "FR-11", "Large in-the-money exposure", "Counterparty flagged BREACH")
def _():
    t = ticket(price=10.0, quantity=60_000.0)
    assert risk.credit_exposure([t], M, AS_OF)[0]["status"] == "BREACH"


@case("UAT-19", "FR-12", "Invoice a delivered physical month", "Amount = quantity x fixed price, payable")
def _():
    t = ticket(delivery_start="2026-09", delivery_end="2026-09", trade_date="2026-08-03", price=80.0)
    ln = S.invoice_lines([t], M, AS_OF)[0]
    assert ln.amount == -400_000.0


@case("UAT-20", "FR-12", "Cash-settle a swap month", "Amount = quantity x (monthly average index - fixed)")
def _():
    t = ticket(product="SWAP", delivery_start="2026-10", delivery_end="2026-10", trade_date="2026-08-03", price=80.0)
    ln = S.invoice_lines([t], M, AS_OF)[0]
    assert abs(ln.amount - 5_000 * (M.fixing("POWER_DE", "2026-10") - 80.0)) < 0.01


@case("UAT-21", "FR-13", "Statement with one wrong amount", "One AMOUNT break, everything else matched")
def _():
    ts = [ticket(delivery_start="2026-07", delivery_end="2026-10", trade_date="2026-06-01", price=80.0)]
    ours = S.invoice_lines(ts, M, AS_OF); theirs = copy.deepcopy(ours); theirs[2].amount += 250
    r = S.reconcile(ours, theirs)
    assert r["summary"]["AMOUNT"] == 1 and r["matched"] == 3


@case("UAT-22", "FR-13", "Statement missing a line and with an unknown line", "MISSING_AT_CPTY and MISSING_IN_OURS")
def _():
    ts = [ticket(delivery_start="2026-07", delivery_end="2026-10", trade_date="2026-06-01", price=80.0)]
    ours = S.invoice_lines(ts, M, AS_OF); theirs = copy.deepcopy(ours[1:])
    theirs.append(S.Line("TL-777777", "2026-10", "ALPSTROM", "PHYSICAL", 1, 1, 1, "EUR"))
    r = S.reconcile(ours, theirs)["summary"]
    assert (r["MISSING_AT_CPTY"], r["MISSING_IN_OURS"]) == (1, 1)


@case("UAT-23", "FR-14", "Report a trade that was amended then cancelled", "Records N, M, C under one UTI; no errors")
def _():
    s = fresh(); s.capture(ticket()); s.amend("TL-100001", {"quantity": 6_000.0}); s.cancel("TL-100001")
    rows = reporting.build(s)
    assert [r["action_type"] for r in rows] == ["N", "M", "C"] and not reporting.check(rows)


@case("UAT-24", "FR-14", "Lifecycle event reported before the NEW", "Rejected by RP-04")
def _():
    s = fresh(); s.capture(ticket()); s.amend("TL-100001", {"quantity": 6_000.0})
    rows = reporting.build(s)[1:]
    assert any(e["rule"] == "RP-04" for e in reporting.check(rows))


def main():
    out, passed = [], 0
    for uid, req, title, expected, fn in CASES:
        try:
            fn(); ok, note = True, ""
        except Exception as e:  # noqa: BLE001
            ok, note = False, f"{type(e).__name__}: {e}"
        passed += ok
        out.append(f"| {uid} | {req} | {title} | {expected} | {'PASS' if ok else 'FAIL'} {note} |")
    reqs = sorted({c[1] for c in CASES})
    md = ["# UAT results", "", f"As-of date {AS_OF}. **{passed}/{len(CASES)} passed**, covering "
          f"{len(reqs)} requirements ({', '.join(reqs)}).", "",
          "| ID | Requirement | Scenario | Expected result | Result |", "|---|---|---|---|---|", *out, ""]
    Path("results").mkdir(exist_ok=True)
    Path("results/uat_results.md").write_text("\n".join(md))
    print(f"{passed}/{len(CASES)} UAT cases passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
