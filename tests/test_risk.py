import pytest

from tradeloop import risk
from tradeloop.reference import FX_TO_USD

AS_OF = "2026-11-20"


def test_positions_net_long_and_short(make):
    ts = [make(trade_id="A", direction="BUY", quantity=10_000.0),
          make(trade_id="B", direction="SELL", quantity=4_000.0, delivery_start="2027-02", delivery_end="2027-02")]
    pos = risk.positions(ts, AS_OF)
    assert pos[("EU_GAS", "GAS_TTF", "2027-01")] == 10_000
    assert pos[("EU_GAS", "GAS_TTF", "2027-02")] == 6_000


def test_delivered_months_drop_out_of_positions(make):
    t = make(delivery_start="2026-09", delivery_end="2026-12", trade_date="2026-08-03")
    assert sorted(m for (_, _, m) in risk.positions([t], AS_OF)) == ["2026-11", "2026-12"]


def test_mtm_sign(make, market):
    buy = make(direction="BUY", price=1.0)
    sell = make(direction="SELL", price=1.0)
    assert risk.trade_mtm(buy, market, AS_OF) > 0 > risk.trade_mtm(sell, market, AS_OF)
    assert risk.trade_mtm(buy, market, AS_OF) == pytest.approx(-risk.trade_mtm(sell, market, AS_OF))


def test_mtm_at_curve_is_near_zero(make, market):
    m = "2027-01"
    t = make(price=market.price("GAS_TTF", m), delivery_start=m, delivery_end=m)
    assert abs(risk.trade_mtm(t, market, AS_OF)) < 1e-6


def test_mtm_converted_to_usd(make, market):
    t = make(price=1.0, delivery_start="2027-01", delivery_end="2027-01")
    raw = (market.price("GAS_TTF", "2027-01") - 1.0) * 10_000 * risk._df(AS_OF, "2027-01")
    assert risk.trade_mtm(t, market, AS_OF) == pytest.approx(raw * FX_TO_USD["EUR"])


def test_pnl_explain_adds_up(make, market):
    ts = [make(trade_id="OLD", trade_date="2026-10-01"),
          make(trade_id="NEW", trade_date=AS_OF, direction="SELL", quantity=3000.0)]
    p = risk.pnl_explain(ts, market, AS_OF)
    assert p["unexplained"] == pytest.approx(0, abs=0.01)
    assert p["total"] == pytest.approx(p["curve_move"] + p["new_trades"], abs=0.01)


def test_var_properties(make, market):
    small = risk.historical_var([make(quantity=1000.0)], market, AS_OF)
    big = risk.historical_var([make(quantity=10_000.0)], market, AS_OF)
    assert 0 < small["var95"] <= small["var99"]
    assert big["var95"] == pytest.approx(10 * small["var95"], rel=1e-6)
    hedged = risk.historical_var([make(trade_id="A"), make(trade_id="B", direction="SELL")], market, AS_OF)
    assert hedged["var95"] == pytest.approx(0, abs=1e-6)


def test_credit_status(make, market):
    t = make(price=1.0, quantity=200_000.0)  # deep in the money for us
    rows = risk.credit_exposure([t], market, AS_OF)
    assert rows[0]["status"] == "BREACH" and rows[0]["utilisation"] > 1
    rows = risk.credit_exposure([make(direction="SELL", price=1.0)], market, AS_OF)
    assert rows[0]["exposure_usd"] == 0 and rows[0]["status"] == "OK"
