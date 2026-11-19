import json

from fastapi.testclient import TestClient

from tradeloop import confirmations, reporting, scenario
from tradeloop.api import create_app


def test_report_actions_follow_lifecycle(store, make):
    store.capture(make())
    store.amend("TL-000001", {"quantity": 11_000.0})
    store.cancel("TL-000001")
    rows = reporting.build(store)
    assert [r["action_type"] for r in rows] == ["N", "M", "C"]
    assert len({r["uti"] for r in rows}) == 1
    assert rows[1]["quantity"] == 11_000.0 and rows[1]["version"] == 2
    assert reporting.check(rows) == []


def test_report_checks_catch_errors():
    bad = [{f: "x" for f in reporting.FIELDS} | {"record_seq": 1, "action_type": "M", "uti": "U1",
                                                    "reporting_lei": "SHORT", "quantity": -1}]
    rules = {e["rule"] for e in reporting.check(bad)}
    assert rules == {"RP-02", "RP-04", "RP-05"}


def _payload(make, **kw):
    t = make(**kw)
    return {k: getattr(t, k) for k in ("trade_id", "trade_date", "book", "trader", "counterparty", "commodity",
                                        "product", "direction", "quantity", "price", "delivery_start", "delivery_end")}


def test_api_end_to_end(make):
    c = TestClient(create_app())
    body = _payload(make)
    assert c.post("/trades", json=body).status_code == 201
    assert c.post("/trades", json=body | {"trade_id": "TL-000002", "counterparty": "DORMANT"}).json()["detail"][0]["rule"] == "VR-03"
    doc = confirmations.render(make(), 2, cpty_ref="CF9")
    assert c.post("/confirmations", json={"text": doc}).json()["status"] == "MATCHED"
    assert c.get("/trades/TL-000001").json()["status"] == "CONFIRMED"
    assert c.patch("/trades/TL-000001", json={"changes": {"price": body["price"] + 0.1}}).json()["version"] == 2
    assert [a["event"] for a in c.get("/trades/TL-000001/audit").json()] == ["CAPTURE", "CONFIRM", "AMEND"]
    assert len(c.get("/positions").json()) == 3
    assert c.get("/risk/var").json()["var95"] > 0
    assert c.get("/reports/transactions").json()["errors"] == []
    assert c.post("/trades/TL-000001/cancel").json()["status"] == "CANCELLED"
    assert c.post("/trades/TL-000001/cancel").status_code == 409
    assert c.get("/trades/NOPE").status_code == 404


def test_scenario_reproduces_published_results(tmp_path):
    """The README quotes results/run_summary.json; a fresh run must match it exactly."""
    fresh = scenario.run(out_dir=str(tmp_path))
    published = json.loads(open("results/run_summary.json").read())
    assert json.loads(json.dumps(fresh)) == published
    assert fresh["capture"]["bad_tickets_rejected_by_expected_rule"] == fresh["capture"]["bad_tickets"]
    assert fresh["confirmations"]["false_matches"] == 0
    assert fresh["reconciliation"]["false_breaks"] == 0
    assert fresh["reconciliation"]["injected_found_with_right_type"] == fresh["reconciliation"]["breaks_injected"]
