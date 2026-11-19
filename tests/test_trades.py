import pytest

from tradeloop.trades import LifecycleError, ValidationError


def rule_of(exc):
    return exc.value.failures[0][0]


@pytest.mark.parametrize("kw,rule", [
    ({"trader": ""}, "VR-01"),
    ({"commodity": "COAL_API2"}, "VR-02"),
    ({"product": "OPTION"}, "VR-02"),
    ({"direction": "HOLD"}, "VR-02"),
    ({"counterparty": "DORMANT"}, "VR-03"),
    ({"counterparty": "NOBODY"}, "VR-03"),
    ({"quantity": -1.0}, "VR-04"),
    ({"price": -5.0}, "VR-04"),
    ({"delivery_start": "2027-04", "delivery_end": "2027-01"}, "VR-05"),
    ({"delivery_start": "2027-13"}, "VR-05"),
    ({"trade_date": "2026-12-01"}, "VR-06"),
])
def test_blocking_rules(store, make, kw, rule):
    with pytest.raises(ValidationError) as e:
        store.capture(make(**kw))
    assert rule_of(e) == rule
    assert store.all() == []


def test_fat_finger_price_rejected(store, make, market):
    ref = market.strip_price("GAS_TTF", "2027-01", "2027-03", "2026-10-01")
    with pytest.raises(ValidationError) as e:
        store.capture(make(price=round(ref * 1.5, 2)))
    assert rule_of(e) == "VR-07"


def test_price_warning_band(store, make, market):
    ref = market.strip_price("GAS_TTF", "2027-01", "2027-03", "2026-10-01")
    t = store.capture(make(price=round(ref * 1.2, 2)))
    assert t.status == "VALIDATED" and t.warnings and t.warnings[0].startswith("VR-07 warning")


def test_duplicate_id_rejected(store, make):
    store.capture(make())
    with pytest.raises(ValidationError):
        store.capture(make())


def test_full_lifecycle_and_audit(store, make):
    store.capture(make(delivery_start="2026-08", delivery_end="2026-09", trade_date="2026-07-01"))
    store.confirm("TL-000001", ref="CF1")
    t = store.settle("TL-000001")
    assert t.status == "SETTLED"
    assert [a["event"] for a in store.audit("TL-000001")] == ["CAPTURE", "CONFIRM", "SETTLE"]


def test_amend_creates_version_and_needs_reconfirmation(store, make):
    store.capture(make())
    store.confirm("TL-000001")
    t = store.amend("TL-000001", {"quantity": 12_000.0}, user="ops")
    assert t.version == 2 and t.status == "VALIDATED"
    vs = store.versions("TL-000001")
    assert [v.quantity for v in vs] == [10_000.0, 12_000.0]
    last = store.audit("TL-000001")[-1]
    assert last["event"] == "AMEND" and "10000.0" in last["detail"] and last["user"] == "ops"


def test_amend_is_revalidated(store, make):
    store.capture(make())
    with pytest.raises(ValidationError):
        store.amend("TL-000001", {"quantity": 0.0})
    assert store.get("TL-000001").quantity == 10_000.0


def test_amend_rejects_non_economic_fields(store, make):
    store.capture(make())
    with pytest.raises(LifecycleError):
        store.amend("TL-000001", {"trade_id": "X"})


@pytest.mark.parametrize("action", ["confirm", "settle", "cancel"])
def test_cancelled_trade_is_frozen(store, make, action):
    store.capture(make())
    store.cancel("TL-000001", reason="booked in error")
    with pytest.raises(LifecycleError):
        getattr(store, action)("TL-000001")


def test_cannot_settle_undelivered(store, make):
    store.capture(make())
    store.confirm("TL-000001")
    with pytest.raises(LifecycleError):
        store.settle("TL-000001")


def test_cannot_settle_unconfirmed(store, make):
    store.capture(make(delivery_start="2026-08", delivery_end="2026-08", trade_date="2026-07-01"))
    with pytest.raises(LifecycleError):
        store.settle("TL-000001")


def test_cancelled_hidden_by_default(store, make):
    store.capture(make())
    store.capture(make(trade_id="TL-000002"))
    store.cancel("TL-000002")
    assert [t.trade_id for t in store.all()] == ["TL-000001"]
    assert len(store.all(include_cancelled=True)) == 2
