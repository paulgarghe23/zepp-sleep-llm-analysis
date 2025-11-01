"""Utility functions for date handling and error management."""

import datetime
from zoneinfo import ZoneInfo


def fail(msg: str):
    """Print error and exit program."""
    print(f"Error: {msg}")
    raise SystemExit(1)


def to_madrid_iso(ts: int) -> str:
    """Convert epoch (seconds) to ISO in Europe/Madrid timezone."""
    if not ts:
        return ""
    utc_dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return utc_dt.astimezone(ZoneInfo("Europe/Madrid")).replace(microsecond=0).isoformat()


def last_n_days_range(days: int = 7, tz_name: str = "Europe/Madrid") -> tuple[str, str]:
    """Return FROM-TO in YYYY-MM-DD format for last N days INCLUDING today."""
    today = datetime.datetime.now(tz=ZoneInfo(tz_name)).date()
    from_date = today - datetime.timedelta(days=days-1)
    return from_date.isoformat(), today.isoformat()


def last_complete_week_range(tz_name: str = "Europe/Madrid") -> tuple[str, str]:
    """
    Return Monday-Sunday of the PREVIOUS complete week (YYYY-MM-DD dates).
    Example: if today is Wednesday 2025-09-10, returns 2025-09-01 to 2025-09-07.
    """
    today = datetime.datetime.now(tz=ZoneInfo(tz_name)).date()
    week_start = today - datetime.timedelta(days=today.weekday() + 7)
    week_end = week_start + datetime.timedelta(days=6)
    return week_start.isoformat(), week_end.isoformat()

