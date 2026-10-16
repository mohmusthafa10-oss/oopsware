"""
Tests for scheduling.selectors: calendar_day_type, schedule_for, is_scheduled_working_day,
and batch variants used by resolve_range.
"""
from datetime import date, time

import pytest

from apps.accounts.models import Role, User
from apps.scheduling.models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule
from apps.scheduling.selectors import (
    DayType,
    calendar_day_type,
    calendar_day_type_from_cache,
    get_calendar_policies_list,
    get_holidays_map,
    get_schedules_map,
    is_scheduled_working_day,
    is_second_saturday,
    schedule_for,
    schedule_for_user_from_cache,
)

PASSWORD = "Str0ng-Pass-9xQ!"


@pytest.fixture
def member(db):
    return User.objects.create_user(
        email="worker@example.com",
        password=PASSWORD,
        full_name="Worker One",
        role=Role.USER,
    )


@pytest.fixture
def policy(db):
    return CalendarPolicy.objects.create(
        effective_from=date(2025, 1, 1),
        sunday_off=True,
        second_saturday_off=True,
    )


@pytest.fixture
def schedule(member):
    return WorkSchedule.objects.create(
        user=member,
        start_time=time(9, 30),
        end_time=time(18, 30),
        late_grace_minutes=15,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
    )


# ---------------------------------------------------------------------------
# is_second_saturday
# ---------------------------------------------------------------------------


def test_is_second_saturday_true():
    # Jan 11 2025 is the 2nd Saturday (day 11, between 8 and 14)
    assert is_second_saturday(date(2025, 1, 11)) is True


def test_is_second_saturday_false_first():
    # Jan 4 2025 is the 1st Saturday
    assert is_second_saturday(date(2025, 1, 4)) is False


def test_is_second_saturday_false_not_saturday():
    assert is_second_saturday(date(2025, 1, 13)) is False  # Monday


# ---------------------------------------------------------------------------
# calendar_day_type — live DB queries
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_day_type_regular_weekday_no_policy():
    """Without a policy, any day is WORKING."""
    d = date(2025, 3, 5)  # Wednesday
    assert calendar_day_type(d) == DayType.WORKING


@pytest.mark.django_db
def test_calendar_day_type_sunday_off(policy):
    # 2025-01-05 is a Sunday
    d = date(2025, 1, 5)
    assert d.weekday() == 6
    assert calendar_day_type(d) == DayType.WEEKLY_OFF


@pytest.mark.django_db
def test_calendar_day_type_second_saturday_off(policy):
    # 2025-01-11 is the 2nd Saturday
    d = date(2025, 1, 11)
    assert calendar_day_type(d) == DayType.WEEKLY_OFF


@pytest.mark.django_db
def test_calendar_day_type_holiday_overrides_sunday():
    """A WORKING_OVERRIDE on Sunday makes it WORKING."""
    CalendarPolicy.objects.create(effective_from=date(2025, 1, 1), sunday_off=True)
    d = date(2025, 1, 5)  # Sunday
    Holiday.objects.create(date=d, name="Special Working Day", kind=HolidayKind.WORKING_OVERRIDE)
    assert calendar_day_type(d) == DayType.WORKING


@pytest.mark.django_db
def test_calendar_day_type_public_holiday():
    d = date(2025, 8, 15)
    Holiday.objects.create(date=d, name="Independence Day")
    assert calendar_day_type(d) == DayType.HOLIDAY


# ---------------------------------------------------------------------------
# schedule_for
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schedule_for_returns_active_schedule(member, schedule):
    result = schedule_for(member, date(2025, 6, 1))
    assert result == schedule


@pytest.mark.django_db
def test_schedule_for_before_effective_from(member, schedule):
    result = schedule_for(member, date(2024, 12, 31))
    assert result is None


@pytest.mark.django_db
def test_schedule_for_non_tracking_user(admin_user):
    result = schedule_for(admin_user, date(2025, 6, 1))
    assert result is None


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="boss@example.com",
        password=PASSWORD,
        full_name="Boss Admin",
        role=Role.ADMIN,
    )


@pytest.mark.django_db
def test_schedule_for_expired(member):
    WorkSchedule.objects.create(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
        effective_to=date(2025, 3, 31),
    )
    # On expiry date → still valid
    assert schedule_for(member, date(2025, 3, 31)) is not None
    # After expiry → no schedule
    assert schedule_for(member, date(2025, 4, 1)) is None


# ---------------------------------------------------------------------------
# is_scheduled_working_day
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_is_scheduled_working_day_true(member, policy, schedule):
    # 2025-01-06 is Monday — working weekday 0 in schedule
    d = date(2025, 1, 6)
    assert d.weekday() == 0
    assert is_scheduled_working_day(member, d) is True


@pytest.mark.django_db
def test_is_scheduled_working_day_sunday_off(member, policy, schedule):
    d = date(2025, 1, 5)  # Sunday
    assert is_scheduled_working_day(member, d) is False


@pytest.mark.django_db
def test_is_scheduled_working_day_override(member, policy, schedule):
    d = date(2025, 1, 5)  # Sunday — normally off
    Holiday.objects.create(date=d, name="Special Day", kind=HolidayKind.WORKING_OVERRIDE)
    # Working override makes it a working day
    assert is_scheduled_working_day(member, d) is True


# ---------------------------------------------------------------------------
# Batch selector functions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_holidays_map(db):
    d1 = date(2025, 8, 15)
    d2 = date(2025, 10, 2)
    Holiday.objects.create(date=d1, name="Independence Day")
    Holiday.objects.create(date=d2, name="Gandhi Jayanti")
    hmap = get_holidays_map(date(2025, 8, 1), date(2025, 10, 31))
    assert d1 in hmap
    assert d2 in hmap
    assert hmap[d1].name == "Independence Day"


@pytest.mark.django_db
def test_get_calendar_policies_list_ordering(db):
    CalendarPolicy.objects.create(effective_from=date(2024, 1, 1))
    CalendarPolicy.objects.create(effective_from=date(2025, 1, 1))
    policies = get_calendar_policies_list()
    assert len(policies) == 2
    assert policies[0].effective_from > policies[1].effective_from


@pytest.mark.django_db
def test_get_schedules_map(member, schedule):
    result = get_schedules_map([member], date(2025, 1, 1), date(2025, 12, 31))
    assert member.id in result
    assert result[member.id][0] == schedule


@pytest.mark.django_db
def test_schedule_for_user_from_cache(member, schedule):
    schedules_by_user = {member.id: [schedule]}
    result = schedule_for_user_from_cache(member.id, date(2025, 6, 1), schedules_by_user)
    assert result == schedule


@pytest.mark.django_db
def test_schedule_for_user_from_cache_miss(member, schedule):
    schedules_by_user = {member.id: [schedule]}
    result = schedule_for_user_from_cache(member.id, date(2024, 1, 1), schedules_by_user)
    assert result is None


@pytest.mark.django_db
def test_calendar_day_type_from_cache_holiday():
    d = date(2025, 8, 15)
    h = Holiday(date=d, name="Ind Day")
    holidays_map = {d: h}
    day_type, is_override = calendar_day_type_from_cache(d, holidays_map, [])
    assert day_type == DayType.HOLIDAY
    assert is_override is False


@pytest.mark.django_db
def test_calendar_day_type_from_cache_override():
    d = date(2025, 1, 5)  # Sunday
    h = Holiday(date=d, name="Working", kind=HolidayKind.WORKING_OVERRIDE)
    holidays_map = {d: h}
    day_type, is_override = calendar_day_type_from_cache(d, holidays_map, [])
    assert day_type == DayType.WORKING
    assert is_override is True
