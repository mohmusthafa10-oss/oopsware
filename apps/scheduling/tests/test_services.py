"""
Tests for scheduling.services: create_schedule_version, create_holiday, update_holiday,
delete_holiday, create_calendar_policy.
"""
from datetime import date, time

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.scheduling.models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule
from apps.scheduling import services

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
def schedule_data():
    return {
        "start_time": time(9, 30),
        "end_time": time(18, 30),
        "late_grace_minutes": 15,
        "absence_cutoff_minutes": 60,
        "working_weekdays": [0, 1, 2, 3, 4, 5],
        "effective_from": date(2025, 1, 1),
    }


# ---------------------------------------------------------------------------
# create_schedule_version
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_schedule_version_first(member, schedule_data, admin_user):
    sched = services.create_schedule_version(member, schedule_data, actor=admin_user)
    assert sched.pk is not None
    assert sched.user == member
    assert sched.effective_to is None


@pytest.mark.django_db
def test_create_schedule_version_closes_previous(member, schedule_data, admin_user):
    sched1 = services.create_schedule_version(member, schedule_data, actor=admin_user)

    new_data = {**schedule_data, "effective_from": date(2025, 6, 1)}
    sched2 = services.create_schedule_version(member, new_data, actor=admin_user)

    sched1.refresh_from_db()
    assert sched1.effective_to == date(2025, 5, 31)
    assert sched2.effective_to is None


@pytest.mark.django_db
def test_create_schedule_version_rejects_past_date(member, schedule_data, admin_user):
    services.create_schedule_version(member, schedule_data, actor=admin_user)
    # Try to create a new schedule with same or earlier date
    old_data = {**schedule_data, "effective_from": date(2024, 12, 1)}
    with pytest.raises(ValidationError, match="must be after the current schedule"):
        services.create_schedule_version(member, old_data, actor=admin_user)


@pytest.mark.django_db
def test_create_schedule_version_rejects_non_tracking(admin_user, schedule_data):
    with pytest.raises(ValidationError, match="Only users who track attendance"):
        services.create_schedule_version(admin_user, schedule_data)


@pytest.mark.django_db
def test_create_schedule_version_missing_effective_from(member):
    with pytest.raises(ValidationError, match="Effective from date is required"):
        services.create_schedule_version(member, {"start_time": time(9, 0), "end_time": time(18, 0)})


# ---------------------------------------------------------------------------
# create_holiday
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_holiday_success(admin_user):
    h = services.create_holiday(
        holiday_date=date(2025, 8, 15),
        name="Independence Day",
        kind=HolidayKind.HOLIDAY,
        actor=admin_user,
    )
    assert h.pk is not None
    assert h.name == "Independence Day"
    assert h.kind == HolidayKind.HOLIDAY


@pytest.mark.django_db
def test_create_holiday_working_override(admin_user):
    h = services.create_holiday(
        holiday_date=date(2025, 10, 4),
        name="Working Saturday",
        kind=HolidayKind.WORKING_OVERRIDE,
        actor=admin_user,
    )
    assert h.kind == HolidayKind.WORKING_OVERRIDE


@pytest.mark.django_db
def test_create_holiday_duplicate_date_raises(admin_user):
    services.create_holiday(
        holiday_date=date(2025, 1, 26),
        name="Republic Day",
        kind=HolidayKind.HOLIDAY,
        actor=admin_user,
    )
    from django.db import IntegrityError
    with pytest.raises((IntegrityError, ValidationError)):
        services.create_holiday(
            holiday_date=date(2025, 1, 26),
            name="Duplicate",
            kind=HolidayKind.HOLIDAY,
            actor=admin_user,
        )


# ---------------------------------------------------------------------------
# update_holiday
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_holiday(admin_user):
    h = services.create_holiday(
        holiday_date=date(2025, 8, 15),
        name="Old Name",
        kind=HolidayKind.HOLIDAY,
        actor=admin_user,
    )
    updated = services.update_holiday(h, name="Independence Day", kind=HolidayKind.HOLIDAY, actor=admin_user)
    assert updated.name == "Independence Day"
    updated.refresh_from_db()
    assert updated.name == "Independence Day"


# ---------------------------------------------------------------------------
# delete_holiday
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_holiday(admin_user):
    h = services.create_holiday(
        holiday_date=date(2025, 8, 15),
        name="Independence Day",
        kind=HolidayKind.HOLIDAY,
        actor=admin_user,
    )
    pk = h.pk
    services.delete_holiday(h, actor=admin_user)
    assert not Holiday.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# create_calendar_policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_calendar_policy(admin_user):
    p = services.create_calendar_policy(
        effective_from=date(2025, 1, 1),
        sunday_off=True,
        second_saturday_off=True,
        actor=admin_user,
    )
    assert p.pk is not None
    assert p.sunday_off is True
    assert p.second_saturday_off is True


@pytest.mark.django_db
def test_create_calendar_policy_defaults(admin_user):
    p = services.create_calendar_policy(effective_from=date(2025, 4, 1), actor=admin_user)
    assert p.sunday_off is True
    assert p.second_saturday_off is True


@pytest.mark.django_db
def test_create_calendar_policy_audit_created(admin_user):
    from apps.audit.models import AuditLog
    count_before = AuditLog.objects.count()
    services.create_calendar_policy(effective_from=date(2025, 7, 1), actor=admin_user)
    assert AuditLog.objects.count() == count_before + 1
