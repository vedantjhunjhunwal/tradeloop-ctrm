import pytest

from tradeloop.market import MarketData
from tradeloop.trades import Trade, TradeStore

AS_OF = "2026-11-20"


@pytest.fixture(scope="session")
def market():
    return MarketData(AS_OF)


@pytest.fixture
def store(market):
    return TradeStore(as_of=AS_OF, market=market)


@pytest.fixture
def make(market):
    def _make(**kw):
        base = dict(trade_id="TL-000001", trade_date="2026-10-01", book="EU_GAS", trader="asharma",
                    counterparty="NORDVIK", commodity="GAS_TTF", product="PHYS_FWD", direction="BUY",
                    quantity=10_000.0, price=0.0, delivery_start="2027-01", delivery_end="2027-03")
        base.update(kw)
        if not base["price"]:
            try:
                on = base["trade_date"] if base["trade_date"] in market.dates else None
                base["price"] = round(market.strip_price(base["commodity"], base["delivery_start"],
                                                         base["delivery_end"], on), 2)
            except (KeyError, ValueError, ZeroDivisionError):
                base["price"] = 30.0  # invalid ticket: price never reached by validation
        return Trade(**base)
    return _make
