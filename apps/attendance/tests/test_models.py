"""
Tests for attendance.models: AttendanceRecord and AttendanceCorrectionRequest
model constraints and clean() validation.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.attendance.models import (
    AttendanceCorrectionRequest,
    AttendanceRecord,
    CorrectionStatus,
    CorrectionType,
)
from apps.scheduling.models import WorkSchedule

PASSWORD = "Str0ng-Pass-9xQ!"
IST = timezone(timedelta(hours=5, minutes=30))


def ist(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST)


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
# AttendanceRecord — unique constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attendance_record_unique_user_work_date(member, schedule):
    AttendanceRecord.objects.create(
        user=member, work_date=date(2025, 1, 6), schedule=schedule,
        check_in_at=ist(2025, 1, 6, 9, 35),
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        AttendanceRecord.objects.create(
            user=member, work_date=date(2025, 1, 6), schedule=schedule,
            check_in_at=ist(2025, 1, 6, 10, 0),
        )


# ---------------------------------------------------------------------------
# AttendanceRecord — clean() validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attendance_record_clean_checkout_before_checkin(member, schedule):
    record = AttendanceRecord(
        user=member,
        work_date=date(2025, 1, 6),
        schedule=schedule,
        check_in_at=ist(2025, 1, 6, 9, 35),
        check_out_at=ist(2025, 1, 6, 8, 0),  # before check-in
    )
    with pytest.raises(ValidationError, match="after check-in"):
        record.full_clean()


@pytest.mark.django_db
def test_attendance_record_clean_non_tracking_user(admin_user, schedule):
    record = AttendanceRecord(
        user=admin_user,
        work_date=date(2025, 1, 6),
        schedule=schedule,
    )
    with pytest.raises(ValidationError, match="Only users who track attendance"):
        record.full_clean()


@pytest.mark.django_db
def test_attendance_record_effective_properties(member, schedule):
    """effective_check_in / effective_check_out prefer corrected values."""
    raw_in = ist(2025, 1, 6, 9, 35)
    corrected_in = ist(2025, 1, 6, 9, 15)
    record = AttendanceRecord(
        user=member,
        work_date=date(2025, 1, 6),
        schedule=schedule,
        check_in_at=raw_in,
        corrected_check_in_at=corrected_in,
    )
    assert record.effective_check_in == corrected_in
    assert record.effective_check_out is None


@pytest.mark.django_db
def test_attendance_record_str(member, schedule):
    record = AttendanceRecord.objects.create(
        user=member, work_date=date(2025, 1, 6), schedule=schedule,
        check_in_at=ist(2025, 1, 6, 9, 35),
    )
    s = str(record)
    assert "Worker One" in s
    assert "2025-01-06" in s


# ---------------------------------------------------------------------------
# AttendanceCorrectionRequest — unique pending constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_correction_request_unique_pending(member, schedule):
    """Only one pending correction per user/date/type."""
    AttendanceCorrectionRequest.objects.create(
        user=member,
        work_date=date(2025, 1, 6),
        type=CorrectionType.CHECK_IN,
        requested_time=time(9, 30),
        reason="First",
    )
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        AttendanceCorrectionRequest.objects.create(
            user=member,
            work_date=date(2025, 1, 6),
            type=CorrectionType.CHECK_IN,
            requested_time=time(9, 45),
            reason="Second",
        )


@pytest.mark.django_db
def test_correction_request_two_types_allowed(member, schedule):
    """One pending check-in and one pending check-out is allowed."""
    AttendanceCorrectionRequest.objects.create(
        user=member,
        work_date=date(2025, 1, 6),
        type=CorrectionType.CHECK_IN,
        requested_time=time(9, 30),
        reason="Check-in correction",
    )
    # This should NOT raise
    AttendanceCorrectionRequest.objects.create(
        user=member,
        work_date=date(2025, 1, 6),
        type=CorrectionType.CHECK_OUT,
        requested_time=time(18, 0),
        reason="Check-out correction",
    )
    assert AttendanceCorrectionRequest.objects.filter(
        user=member, work_date=date(2025, 1, 6)
    ).count() == 2


@pytest.mark.django_db
def test_correction_request_str(member):
    req = AttendanceCorrectionRequest(
        user=member,
        work_date=date(2025, 1, 6),
        type=CorrectionType.CHECK_IN,
        requested_time=time(9, 30),
        reason="Test",
        status=CorrectionStatus.PENDING,
    )
    s = str(req)
    assert "Worker One" in s
    assert "check_in" in s
