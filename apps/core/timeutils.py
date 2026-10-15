"""All date/time construction goes through here so "which day is it" has one answer.

Timestamps are stored as aware UTC. Work dates are IST calendar dates.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIME_ZONE)


def local_now() -> datetime:
    return timezone.localtime(timezone.now())


def local_date(moment: datetime | None = None) -> date:
    """The IST calendar date of `moment` (default: now)."""
    if moment is None:
        moment = timezone.now()
    return timezone.localtime(moment, local_tz()).date()


def make_aware_local(day: date, at: time) -> datetime:
    """Combine an IST date and wall-clock time into an aware datetime."""
    return datetime.combine(day, at, tzinfo=local_tz())