"""
Tests for scheduling.models: CalendarPolicy, Holiday, WorkSchedule.

Covers model constraints, clean() validation, and __str__ methods.
"""
from datetime import date, time

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.scheduling.models import (
    CalendarPolicy,
    Holiday,
    HolidayKind,
    WorkSchedule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def admin_user(db):
    return User.objects.create_user(
        email="boss@example.com",
        password=PASSWORD,
        full_name="Boss Admin",
        role=Role.ADMIN,
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
# CalendarPolicy tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_policy_str():
    p = CalendarPolicy(effective_from=date(2025, 1, 1), sunday_off=True, second_saturday_off=True)
    assert "2025-01-01" in str(p)


@pytest.mark.django_db
def test_calendar_policy_create_and_ordering(db):
    CalendarPolicy.objects.create(effective_from=date(2025, 1, 1))
    CalendarPolicy.objects.create(effective_from=date(2026, 1, 1))
    policies = list(CalendarPolicy.objects.all())
    # default ordering is -effective_from
    assert policies[0].effective_from > policies[1].effective_from


@pytest.mark.django_db
def test_calendar_policy_unique_effective_from(db):
    CalendarPolicy.objects.create(effective_from=date(2025, 6, 1))
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        CalendarPolicy.objects.create(effective_from=date(2025, 6, 1))


# ---------------------------------------------------------------------------
# Holiday tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_holiday_create_default_kind(db):
    h = Holiday.objects.create(date=date(2025, 8, 15), name="Independence Day")
    assert h.kind == HolidayKind.HOLIDAY
    assert "Independence Day" in str(h)


@pytest.mark.django_db
def test_holiday_working_override(db):
    h = Holiday.objects.create(
        date=date(2025, 10, 2),
        name="Working Saturday",
        kind=HolidayKind.WORKING_OVERRIDE,
    )
    assert h.kind == HolidayKind.WORKING_OVERRIDE
    assert "Working override" in h.get_kind_display()


@pytest.mark.django_db
def test_holiday_unique_date(db):
    Holiday.objects.create(date=date(2025, 1, 26), name="Republic Day")
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        Holiday.objects.create(date=date(2025, 1, 26), name="Dup")


# ---------------------------------------------------------------------------
# WorkSchedule model validation tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schedule_clean_end_before_start(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(18, 0),
        end_time=time(9, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="End time must be after start time"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_cutoff_gt_grace(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=60,
        absence_cutoff_minutes=30,  # less than grace → invalid
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="Absence cutoff minutes must be greater than late grace"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_cutoff_exceeds_shift(member):
    """Start + absence_cutoff > end → invalid."""
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(10, 0),  # 60 min shift
        late_grace_minutes=0,
        absence_cutoff_minutes=120,  # 2 hrs - exceeds shift
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="absence cutoff cannot exceed schedule end"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_effective_to_before_from(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 6, 1),
        effective_to=date(2025, 5, 1),  # before effective_from
    )
    with pytest.raises(ValidationError, match="effective_to must be on or after"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_empty_weekdays(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[],
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="Working weekdays cannot be empty"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_invalid_weekday(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 7],  # 7 is invalid
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="Invalid weekday"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_duplicate_weekday(member):
    sched = WorkSchedule(
        user=member,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 0],  # duplicate Monday
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="Duplicate weekday"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_clean_non_tracking_user(admin_user):
    """Admin users don't track attendance — schedule must be rejected."""
    sched = WorkSchedule(
        user=admin_user,
        start_time=time(9, 0),
        end_time=time(18, 0),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        effective_from=date(2025, 1, 1),
    )
    with pytest.raises(ValidationError, match="Only users who track attendance"):
        sched.full_clean()


@pytest.mark.django_db
def test_schedule_str(schedule):
    s = str(schedule)
    assert "Worker One" in s
    assert "09:30" in s
