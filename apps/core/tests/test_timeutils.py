from datetime import date, datetime, time, timezone

from apps.core import timeutils


def test_local_date_uses_ist_not_utc():
    # 18:30 UTC on 1 Jan is 00:00 IST on 2 Jan.
    moment = datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)
    assert timeutils.local_date(moment) == date(2026, 1, 2)


def test_late_evening_ist_stays_on_same_day():
    # 23:50 IST on 5 Mar is 18:20 UTC the same day.
    moment = datetime(2026, 3, 5, 18, 20, tzinfo=timezone.utc)
    assert timeutils.local_date(moment) == date(2026, 3, 5)


def test_make_aware_local_has_ist_offset():
    dt = timeutils.make_aware_local(date(2026, 3, 5), time(9, 30))
    assert dt.utcoffset().total_seconds() == 5.5 * 3600
    assert dt.astimezone(timezone.utc).hour == 4 and dt.astimezone(timezone.utc).minute == 0
    