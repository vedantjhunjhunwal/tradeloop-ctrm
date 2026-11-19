import copy

import pytest

from tradeloop import settlement as S
from tradeloop.trades import TradeStore


@pytest.fixture
def delivered(make):
    return [make(trade_id="TL-1", delivery_start="2026-08", delivery_end="2026-09", trade_date="2026-07-01",
                 direction="BUY", quantity=1000.0, price=30.0),
            make(trade_id="TL-2", product="SWAP", delivery_start="2026-09", delivery_end="2026-12",
                 trade_date="2026-07-01", direction="SELL", quantity=2000.0, price=31.0)]


def test_physical_invoice_amounts(delivered, market):
    lines = [ln for ln in S.invoice_lines(delivered, market, "2026-11-20") if ln.trade_id == "TL-1"]
    assert [(ln.month, ln.amount) for ln in lines] == [("2026-08", -30000.0), ("2026-09", -30000.0)]


def test_swap_cash_settles_against_fixing(delivered, market):
    lines = [ln for ln in S.invoice_lines(delivered, market, "2026-11-20") if ln.trade_id == "TL-2"]
    assert [ln.month for ln in lines] == ["2026-09", "2026-10"]  # Nov/Dec not delivered yet
    for ln in lines:
        fix = market.fixing("GAS_TTF", ln.month)
        assert ln.price == fix
        assert ln.amount == pytest.approx(-1 * 2000 * (fix - 31.0), abs=0.01)


def test_fixing_is_monthly_average(market):
    days = [d for d in market.dates if d.startswith("2026-09")]
    avg = sum(market.price("BRENT", "2026-09", d) for d in days) / len(days)
    assert market.fixing("BRENT", "2026-09") == pytest.approx(avg, abs=1e-4)


def test_netting_by_counterparty_month(delivered, market):
    net = S.netting(S.invoice_lines(delivered, market, "2026-11-20"))
    assert ("NORDVIK", "2026-09", "EUR") in net


def _pair(delivered, market):
    ours = S.invoice_lines(delivered, market, "2026-11-20")
    return ours, copy.deepcopy(ours)


def test_clean_statement_fully_matches(delivered, market):
    ours, theirs = _pair(delivered, market)
    r = S.reconcile(ours, theirs)
    assert r["matched"] == len(ours) and r["breaks"] == []


def test_each_break_type_detected(delivered, market):
    ours, theirs = _pair(delivered, market)
    theirs[0].amount += 125.0                     # AMOUNT
    theirs[1].quantity += 500                     # QUANTITY
    dropped = theirs.pop(2)                       # MISSING_AT_CPTY
    theirs.append(copy.deepcopy(theirs[-1]))      # DUPLICATE
    theirs.append(S.Line("TL-999", "2026-10", "NORDVIK", "PHYSICAL", 1, 1, -1, "EUR"))  # MISSING_IN_OURS
    r = S.reconcile(ours, theirs)
    assert r["summary"] == {"MISSING_AT_CPTY": 1, "MISSING_IN_OURS": 1, "DUPLICATE": 1, "QUANTITY": 1, "AMOUNT": 1}
    assert any(b["trade_id"] == dropped.trade_id and b["type"] == "MISSING_AT_CPTY" for b in r["breaks"])


def test_tolerance(delivered, market):
    ours, theirs = _pair(delivered, market)
    theirs[0].amount += 0.009
    assert S.reconcile(ours, theirs)["breaks"] == []
