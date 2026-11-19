"""Synthetic forward curves and monthly index fixings.

The generator is seeded, so every run produces the same market. Each commodity
has one common daily shock shared by all tenors plus a smaller tenor-specific
shock; gas and power carry a winter premium.
"""
import math
import random
from datetime import date, timedelta

from . import months
from .reference import COMMODITIES

WINTER = {"POWER_DE": 0.18, "GAS_TTF": 0.25, "BRENT": 0.0}


def _season(code: str, month: str) -> float:
    mo = int(month[5:])
    w = WINTER[code]
    # +w in Dec/Jan, -w in Jun/Jul
    return 1 + w * math.cos((mo - 1) * math.pi / 6) * (1 if mo in (11, 12, 1, 2) else 0.6)


def business_days(end: date, n: int) -> list[str]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


class MarketData:
    def __init__(self, as_of: str, n_days: int = 260, first_month: str = "2025-11",
                 last_month: str = "2027-12", seed: int = 7):
        self.as_of = as_of
        self.dates = business_days(date.fromisoformat(as_of), n_days)
        self.tenors = months.month_range(first_month, last_month)
        rng = random.Random(seed)
        self._px: dict[str, dict[str, dict[str, float]]] = {d: {} for d in self.dates}
        for code, com in COMMODITIES.items():
            dvol = com.vol / math.sqrt(252)
            level = {m: 0.0 for m in self.tenors}
            for d in self.dates:
                common = rng.gauss(0, dvol * 0.9)
                row = {}
                for m in self.tenors:
                    level[m] += common + rng.gauss(0, dvol * 0.35)
                    row[m] = round(com.base_price * _season(code, m) * math.exp(level[m]), 4)
                self._px[d][code] = row

    def curve(self, code: str, on: str | None = None) -> dict[str, float]:
        return self._px[on or self.dates[-1]][code]

    def price(self, code: str, month: str, on: str | None = None) -> float:
        return self.curve(code, on)[month]

    def strip_price(self, code: str, start: str, end: str, on: str | None = None) -> float:
        """Average forward price over a delivery strip (equal monthly volumes)."""
        ms = months.month_range(start, end)
        c = self.curve(code, on)
        return sum(c[m] for m in ms) / len(ms)

    def previous_date(self, on: str | None = None) -> str:
        i = self.dates.index(on or self.dates[-1])
        return self.dates[i - 1]

    def fixing(self, code: str, month: str) -> float:
        """Monthly index = average of that tenor's daily prices during the month."""
        vals = [self._px[d][code][month] for d in self.dates if d[:7] == month]
        if not vals:
            raise KeyError(f"no fixing data for {code} {month}")
        return round(sum(vals) / len(vals), 4)

    def daily_changes(self, code: str, month: str, window: int = 250) -> list[float]:
        days = self.dates[-(window + 1):]
        return [self._px[b][code][month] - self._px[a][code][month] for a, b in zip(days, days[1:])]
