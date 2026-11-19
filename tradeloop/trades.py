"""Trade capture: validation rules, lifecycle state machine and a SQLite store
with full version history and an audit log.

Lifecycle
---------
    VALIDATED --confirm--> CONFIRMED --settle--> SETTLED
        ^   |                  |
        |   +----cancel--------+--> CANCELLED
        +---- amend (new version, needs re-confirmation) ----+

A trade that fails a blocking validation rule is never stored (REJECTED).
"""
import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from . import months
from .reference import COMMODITIES, COUNTERPARTIES, PRODUCTS

STATES = {"VALIDATED", "CONFIRMED", "SETTLED", "CANCELLED"}
TRANSITIONS = {
    ("VALIDATED", "confirm"): "CONFIRMED",
    ("VALIDATED", "amend"): "VALIDATED",
    ("CONFIRMED", "amend"): "VALIDATED",
    ("VALIDATED", "cancel"): "CANCELLED",
    ("CONFIRMED", "cancel"): "CANCELLED",
    ("CONFIRMED", "settle"): "SETTLED",
}
AMENDABLE = ("quantity", "price", "delivery_start", "delivery_end", "counterparty")
FAT_FINGER_BAND = 0.30   # VR-07: price must be within +/-30% of the curve


class ValidationError(Exception):
    def __init__(self, failures: list[tuple[str, str]]):
        self.failures = failures
        super().__init__("; ".join(f"{c}: {m}" for c, m in failures))


class LifecycleError(Exception):
    pass


@dataclass
class Trade:
    trade_id: str
    trade_date: str              # YYYY-MM-DD
    book: str
    trader: str
    counterparty: str
    commodity: str
    product: str                 # PHYS_FWD | SWAP
    direction: str               # BUY | SELL (our side)
    quantity: float              # per delivery month
    price: float                 # fixed price
    delivery_start: str          # YYYY-MM
    delivery_end: str            # YYYY-MM
    version: int = 1
    status: str = "VALIDATED"
    warnings: list = field(default_factory=list)

    @property
    def unit(self) -> str:
        return COMMODITIES[self.commodity].unit

    @property
    def currency(self) -> str:
        return COMMODITIES[self.commodity].currency

    @property
    def sign(self) -> int:
        return 1 if self.direction == "BUY" else -1

    def delivery_months(self) -> list[str]:
        return months.month_range(self.delivery_start, self.delivery_end)


def validate(t: Trade, as_of: str, market=None) -> list[str]:
    """Run validation rules VR-01..VR-07. Raises ValidationError on blocking
    failures; returns non-blocking warnings."""
    fails = []
    required = ("trade_id", "trade_date", "book", "trader", "counterparty", "commodity",
                "product", "direction", "delivery_start", "delivery_end")
    missing = [f for f in required if not getattr(t, f)]
    if missing:
        fails.append(("VR-01", f"missing fields: {', '.join(missing)}"))
    if t.commodity not in COMMODITIES:
        fails.append(("VR-02", f"unknown commodity {t.commodity!r}"))
    if t.product not in PRODUCTS:
        fails.append(("VR-02", f"unknown product {t.product!r}"))
    if t.direction not in ("BUY", "SELL"):
        fails.append(("VR-02", f"direction must be BUY or SELL, got {t.direction!r}"))
    cp = COUNTERPARTIES.get(t.counterparty)
    if cp is None:
        fails.append(("VR-03", f"unknown counterparty {t.counterparty!r}"))
    elif not cp.active:
        fails.append(("VR-03", f"counterparty {t.counterparty} is inactive"))
    if not (t.quantity and t.quantity > 0):
        fails.append(("VR-04", "quantity must be positive"))
    if not (t.price and t.price > 0):
        fails.append(("VR-04", "price must be positive"))
    try:
        if months.to_int(t.delivery_end) < months.to_int(t.delivery_start):
            fails.append(("VR-05", "delivery end is before delivery start"))
    except (ValueError, AttributeError):
        fails.append(("VR-05", "delivery period must be YYYY-MM"))
    if t.trade_date and t.trade_date > as_of:
        fails.append(("VR-06", f"trade date {t.trade_date} is after as-of date {as_of}"))
    if fails:
        raise ValidationError(fails)

    warnings = []
    if market is not None:
        on = t.trade_date if t.trade_date in market.dates else None
        ref = market.strip_price(t.commodity, t.delivery_start, t.delivery_end, on)
        if abs(t.price / ref - 1) > FAT_FINGER_BAND:
            raise ValidationError([("VR-07", f"price {t.price} is more than "
                                    f"{FAT_FINGER_BAND:.0%} away from the strip curve {ref:.2f}")])
        if abs(t.price / ref - 1) > FAT_FINGER_BAND / 2:
            warnings.append(f"VR-07 warning: price {t.price} is {t.price / ref - 1:+.0%} vs curve")
    return warnings


class TradeStore:
    """SQLite-backed trade store. Every change writes a new row to
    trade_versions and an entry to audit_log."""

    def __init__(self, path: str = ":memory:", as_of: str = "2026-11-20", market=None):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.as_of = as_of
        self.market = market
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (trade_id TEXT PRIMARY KEY, version INT, status TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS trade_versions (trade_id TEXT, version INT, body TEXT,
                PRIMARY KEY (trade_id, version));
            CREATE TABLE IF NOT EXISTS audit_log (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
                trade_id TEXT, version INT, event TEXT, user TEXT, detail TEXT);
        """)

    # -- persistence helpers -------------------------------------------------
    def _write(self, t: Trade, event: str, user: str, detail: dict):
        body = json.dumps(asdict(t))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO trades VALUES (?,?,?,?)",
                            (t.trade_id, t.version, t.status, body))
            self.db.execute("INSERT OR REPLACE INTO trade_versions VALUES (?,?,?)",
                            (t.trade_id, t.version, body))
            self.db.execute("INSERT INTO audit_log (ts, trade_id, version, event, user, detail) "
                            "VALUES (?,?,?,?,?,?)",
                            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             t.trade_id, t.version, event, user, json.dumps(detail)))

    def get(self, trade_id: str) -> Trade:
        row = self.db.execute("SELECT body FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
        if row is None:
            raise KeyError(trade_id)
        return Trade(**json.loads(row[0]))

    def all(self, include_cancelled: bool = False) -> list[Trade]:
        rows = self.db.execute("SELECT body FROM trades ORDER BY trade_id").fetchall()
        ts = [Trade(**json.loads(r[0])) for r in rows]
        return ts if include_cancelled else [t for t in ts if t.status != "CANCELLED"]

    def versions(self, trade_id: str) -> list[Trade]:
        rows = self.db.execute("SELECT body FROM trade_versions WHERE trade_id=? ORDER BY version",
                               (trade_id,)).fetchall()
        return [Trade(**json.loads(r[0])) for r in rows]

    def audit(self, trade_id: str | None = None) -> list[dict]:
        q = "SELECT ts, trade_id, version, event, user, detail FROM audit_log"
        rows = self.db.execute(q + (" WHERE trade_id=?" if trade_id else "") + " ORDER BY seq",
                               (trade_id,) if trade_id else ()).fetchall()
        return [dict(zip(("ts", "trade_id", "version", "event", "user", "detail"), r)) for r in rows]

    # -- lifecycle -----------------------------------------------------------
    def _transition(self, t: Trade, action: str) -> str:
        nxt = TRANSITIONS.get((t.status, action))
        if nxt is None:
            raise LifecycleError(f"cannot {action} trade {t.trade_id} in status {t.status}")
        return nxt

    def capture(self, t: Trade, user: str = "system") -> Trade:
        exists = self.db.execute("SELECT 1 FROM trades WHERE trade_id=?", (t.trade_id,)).fetchone()
        if exists:
            raise ValidationError([("VR-01", f"duplicate trade id {t.trade_id}")])
        t.warnings = validate(t, self.as_of, self.market)
        t.status, t.version = "VALIDATED", 1
        self._write(t, "CAPTURE", user, {"warnings": t.warnings})
        return t

    def amend(self, trade_id: str, changes: dict, user: str = "system") -> Trade:
        old = self.get(trade_id)
        bad = set(changes) - set(AMENDABLE)
        if bad:
            raise LifecycleError(f"fields not amendable: {sorted(bad)}")
        status = self._transition(old, "amend")
        new = replace(old, **changes, version=old.version + 1, status=status)
        new.warnings = validate(new, self.as_of, self.market)
        diff = {k: [getattr(old, k), v] for k, v in changes.items() if getattr(old, k) != v}
        self._write(new, "AMEND", user, diff)
        return new

    def confirm(self, trade_id: str, user: str = "system", ref: str = "") -> Trade:
        t = self.get(trade_id)
        t.status = self._transition(t, "confirm")
        self._write(t, "CONFIRM", user, {"confirmation_ref": ref})
        return t

    def cancel(self, trade_id: str, user: str = "system", reason: str = "") -> Trade:
        t = self.get(trade_id)
        t.status = self._transition(t, "cancel")
        self._write(t, "CANCEL", user, {"reason": reason})
        return t

    def settle(self, trade_id: str, user: str = "system") -> Trade:
        t = self.get(trade_id)
        if months.to_int(t.delivery_end) >= months.to_int(months.month_of(self.as_of)):
            raise LifecycleError(f"trade {trade_id} still has undelivered months")
        t.status = self._transition(t, "settle")
        self._write(t, "SETTLE", user, {})
        return t
