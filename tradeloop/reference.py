"""Static reference data: commodities, counterparties, books.

All counterparties and LEIs are fictional.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Commodity:
    code: str
    name: str
    unit: str
    currency: str
    index: str          # floating index used for swaps
    base_price: float   # level used by the synthetic curve generator
    vol: float          # annualised volatility for the synthetic curve


COMMODITIES = {
    "POWER_DE": Commodity("POWER_DE", "German Baseload Power", "MWh", "EUR", "EEX-DE-BASE-M", 82.0, 0.45),
    "GAS_TTF": Commodity("GAS_TTF", "TTF Natural Gas", "MWh", "EUR", "ICE-TTF-M", 34.0, 0.50),
    "BRENT": Commodity("BRENT", "Brent Crude Oil", "bbl", "USD", "ICE-BRENT-M", 74.0, 0.30),
}

PRODUCTS = {"PHYS_FWD", "SWAP"}

# FX into the reporting currency (USD). Fixed for the demo.
FX_TO_USD = {"USD": 1.0, "EUR": 1.08}


@dataclass(frozen=True)
class Counterparty:
    code: str
    name: str
    lei: str
    credit_limit_usd: float
    active: bool = True


COUNTERPARTIES = {
    c.code: c for c in [
        Counterparty("NORDVIK", "Nordvik Energy AS", "5493001NORDVIK00EN01", 10_000_000),
        Counterparty("ALPSTROM", "Alpstrom Handel GmbH", "5299002ALPSTROMHD002", 9_000_000),
        Counterparty("GULFSTAR", "Gulfstar Petroleum DMCC", "2549003GULFSTARPT003", 15_000_000),
        Counterparty("THAMES", "Thames Gas Trading Ltd", "2138004THAMESGAST004", 12_000_000),
        Counterparty("ORIENTO", "Oriento Commodities Pte", "5493005ORIENTOCMD005", 12_000_000),
        Counterparty("BALTIC", "Baltic Utility Supply SA", "2594006BALTICUTIL006", 6_000_000),
        Counterparty("DORMANT", "Dormant Resources Ltd", "2138007DORMANTRES007", 1_000_000, active=False),
    ]
}

# Our own legal entity
OUR_ENTITY = Counterparty("MERIDIAN", "Meridian Trading Ltd", "2138000MERIDIANTR000", 0)

BOOKS = {"EU_POWER", "EU_GAS", "CRUDE"}
BOOK_FOR = {"POWER_DE": "EU_POWER", "GAS_TTF": "EU_GAS", "BRENT": "CRUDE"}
