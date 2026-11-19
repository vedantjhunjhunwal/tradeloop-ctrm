import itertools

import pytest

from tradeloop import confirmations as C


@pytest.mark.parametrize("template,commodity,product,direction,cp", list(itertools.product(
    range(3), ["POWER_DE", "GAS_TTF", "BRENT"], ["PHYS_FWD", "SWAP"], ["BUY", "SELL"], ["THAMES", "GULFSTAR"])))
def test_round_trip_every_layout(make, template, commodity, product, direction, cp):
    """Every template x commodity x product x side reads back exactly.
    THAMES and GULFSTAR are chosen because their names contain commodity words."""
    qty = 25_000.0 if commodity == "BRENT" else 12_500.0
    t = make(commodity=commodity, product=product, direction=direction, counterparty=cp, quantity=qty)
    doc = C.render(t, template, cpty_ref="CF000001")
    e = C.parse(doc)
    assert e.missing == [], doc
    assert C.match(e, t)["status"] == "MATCHED", (doc, e)
    assert e.our_ref == t.trade_id


@pytest.mark.parametrize("field,value", [
    ("price", None), ("quantity", None), ("delivery_end", "2027-04"), ("direction", "SELL")])
def test_mismatch_flags_the_right_field(make, field, value):
    t = make()
    ov = {"price": t.price + 0.5, "quantity": t.quantity + 1000}.get(field, value)
    for template in range(3):
        e = C.parse(C.render(t, template, {field: ov}, cpty_ref="CF1"))
        res = C.match(e, t)
        assert res["status"] == "MISMATCH" and res["fields"] == [field]


def test_small_rounding_difference_tolerated(make):
    t = make(price=20.0)
    e = C.parse(C.render(t, 0))
    e.price = 20.004
    assert C.match(e, t)["status"] == "MATCHED"


def test_illegible_price_goes_to_review(make):
    t = make()
    doc = C.render(t, 1).replace(f"{t.price:.2f}", "[illegible]")
    res = C.match(C.parse(doc), t)
    assert res == {"status": "UNREADABLE", "fields": ["price"]}


def test_month_formats():
    assert C._month("Jan-2027") == "2027-01"
    assert C._month("September 27") == "2027-09"
    assert C._month("2027-03") == "2027-03"
