"""Small helpers for monthly delivery periods written as 'YYYY-MM'."""


def to_int(m: str) -> int:
    y, mo = m.split("-")
    return int(y) * 12 + int(mo) - 1


def from_int(n: int) -> str:
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    return [from_int(n) for n in range(to_int(start), to_int(end) + 1)]


def add(m: str, k: int) -> str:
    return from_int(to_int(m) + k)


def month_of(date_iso: str) -> str:
    return date_iso[:7]
