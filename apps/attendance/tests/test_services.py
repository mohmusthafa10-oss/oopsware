"""
Tests for attendance.services: resolve_day, summarize, check_in, check_out,
submit_correction, review_correction.

All datetime manipulation uses time-machine to freeze time so tests are
deterministic regardless of when they run.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest
import time_machine
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, User
from apps.attendance.models import (
    AttendanceCorrectionRequest,
    AttendanceRecord,
    CorrectionStatus,
    CorrectionType,
)
from apps.attendance import services
from apps.attendance.services import (
    CheckoutState,
    DayStatus,
    DayType,
    Presence,
    resolve_day,
    summarize,
)
from apps.scheduling.models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule

PASSWORD = "Str0ng-Pass-9xQ!"

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


def ist(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=IST)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def policy(db):
    return CalendarPolicy.objects.create(
        effective_from=date(2025, 1, 1),
        sunday_off=True,
        second_saturday_off=True,
    )


@pytest.fixture
def schedule(member):
    """9:30–18:30, grace=15min, cutoff=60min, Mon–Sat (0-5)."""
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
# resolve_day — DayType logic
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_resolve_day_future(member, schedule, policy):
    """A future date returns DayType.FUTURE."""
    # Freeze "today" to 2025-06-01 09:00 IST
    now = ist(2025, 6, 1, 9, 0)
    future = date(2025, 6, 10)
    status = resolve_day(member, future, now=now)
    assert status.day_type == DayType.FUTURE
    assert status.counts_in_denominator is False
    assert status.counts_as_present is False


@pytest.mark.django_db
def test_resolve_day_no_schedule(member, policy):
    """Before any schedule is defined → NO_SCHEDULE."""
    now = ist(2025, 3, 1, 9, 0)
    status = resolve_day(member, date(2025, 3, 1), now=now)
    assert status.day_type == DayType.NO_SCHEDULE


@pytest.mark.django_db
def test_resolve_day_weekly_off_sunday(member, schedule, policy):
    """Sunday with policy.sunday_off=True → WEEKLY_OFF."""
    # 2025-01-05 is Sunday
    d = date(2025, 1, 5)
    now = ist(2025, 1, 5, 20, 0)
    status = resolve_day(member, d, now=now)
    assert status.day_type == DayType.WEEKLY_OFF
    assert status.presence == Presence.NOT_APPLICABLE


@pytest.mark.django_db
def test_resolve_day_holiday(member, schedule):
    """A public holiday → DayType.HOLIDAY."""
    d = date(2025, 8, 15)
    Holiday.objects.create(date=d, name="Independence Day")
    now = ist(2025, 8, 15, 20, 0)
    status = resolve_day(member, d, now=now)
    assert status.day_type == DayType.HOLIDAY


@pytest.mark.django_db
def test_resolve_day_scheduled_off(policy):
    """A day not in schedule.working_weekdays → SCHEDULED_OFF.

    Uses a fresh user with a Mon–Fri only schedule (no prior schedule to conflict with).
    """
    # Create a fresh member so there's no prior open-ended schedule to conflict with
    fri_member = User.objects.create_user(
        email="fri_only@example.com",
        password="Str0ng-Pass-9xQ!",
        full_name="Fri Worker",
        role=Role.USER,
    )
    WorkSchedule.objects.create(
        user=fri_member,
        start_time=time(9, 30),
        end_time=time(18, 30),
        late_grace_minutes=0,
        absence_cutoff_minutes=60,
        working_weekdays=[0, 1, 2, 3, 4],  # Mon-Fri only
        effective_from=date(2025, 1, 1),
    )
    # 2025-02-01 is Saturday — not in [0,1,2,3,4]
    d = date(2025, 2, 1)
    assert d.weekday() == 5
    now = ist(2025, 2, 1, 20, 0)
    status = resolve_day(fri_member, d, now=now)
    assert status.day_type == DayType.SCHEDULED_OFF



@pytest.mark.django_db
def test_resolve_day_present_on_time(member, schedule, policy):
    """Check-in before grace deadline → PRESENT, not late."""
    d = date(2025, 1, 6)  # Monday
    # Check-in at 9:35 IST — after start (9:30) but within grace (9:45)
    check_in = ist(2025, 1, 6, 9, 35)
    AttendanceRecord.objects.create(
        user=member,
        work_date=d,
        schedule=schedule,
        check_in_at=check_in,
        check_out_at=ist(2025, 1, 6, 18, 30),
    )
    now = ist(2025, 1, 6, 20, 0)
    status = resolve_day(member, d, now=now)
    assert status.presence == Presence.PRESENT
    assert status.is_late is False
    assert status.counts_as_present is True
    assert status.checkout_state == CheckoutState.DONE


@pytest.mark.django_db
def test_resolve_day_present_late(member, schedule, policy):
    """Check-in after grace but before cutoff → PRESENT and late."""
    d = date(2025, 1, 6)
    # Grace ends 9:45; cutoff at 10:30
    check_in = ist(2025, 1, 6, 9, 50)
    AttendanceRecord.objects.create(
        user=member,
        work_date=d,
        schedule=schedule,
        check_in_at=check_in,
        check_out_at=ist(2025, 1, 6, 18, 30),
    )
    now = ist(2025, 1, 6, 20, 0)
    status = resolve_day(member, d, now=now)
    assert status.presence == Presence.PRESENT
    assert status.is_late is True
    assert status.arrived_after_cutoff is False


@pytest.mark.django_db
def test_resolve_day_arrived_after_cutoff(member, schedule, policy):
    """Check-in at or after cutoff (10:30) → after_cutoff = True."""
    d = date(2025, 1, 6)
    check_in = ist(2025, 1, 6, 10, 30)  # exactly at cutoff
    AttendanceRecord.objects.create(
        user=member,
        work_date=d,
        schedule=schedule,
        check_in_at=check_in,
        check_out_at=ist(2025, 1, 6, 18, 30),
    )
    now = ist(2025, 1, 6, 20, 0)
    status = resolve_day(member, d, now=now)
    assert status.arrived_after_cutoff is True


@pytest.mark.django_db
def test_resolve_day_absent(member, schedule, policy):
    """No check-in after cutoff → ABSENT."""
    d = date(2025, 1, 6)
    # Cutoff is 10:30; now is past that
    now = ist(2025, 1, 6, 11, 0)
    status = resolve_day(member, d, now=now)
    assert status.presence == Presence.ABSENT
    assert status.counts_in_denominator is True
    assert status.counts_as_present is False


@pytest.mark.django_db
def test_resolve_day_not_yet(member, schedule, policy):
    """No check-in before cutoff → NOT_YET (today's open window)."""
    d = date(2025, 1, 6)
    # Now is 9:40 which is before cutoff 10:30
    now = ist(2025, 1, 6, 9, 40)
    status = resolve_day(member, d, now=now)
    assert status.presence == Presence.NOT_YET
    assert status.counts_in_denominator is False


@pytest.mark.django_db
def test_resolve_day_missing_checkout(member, schedule, policy):
    """Past day with check-in but no check-out → MISSING checkout."""
    d = date(2025, 1, 6)
    AttendanceRecord.objects.create(
        user=member,
        work_date=d,
        schedule=schedule,
        check_in_at=ist(2025, 1, 6, 9, 35),
    )
    # Now is well into next day
    now = ist(2025, 1, 7, 9, 0)
    status = resolve_day(member, d, now=now)
    assert status.checkout_state == CheckoutState.MISSING


@pytest.mark.django_db
def test_resolve_day_inactive_after_deactivation(member, schedule, policy):
    """Days after deactivation → INACTIVE."""
    member.deactivated_at = ist(2025, 3, 15, 18, 0)
    member.save()
    now = ist(2025, 3, 20, 20, 0)
    status = resolve_day(member, date(2025, 3, 20), now=now)
    assert status.day_type == DayType.INACTIVE


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


def make_status(
    day_type=DayType.WORKING,
    presence=Presence.PRESENT,
    is_late=False,
    arrived_after_cutoff=False,
    checkout_state=CheckoutState.DONE,
    counts_in_denominator=True,
    counts_as_present=True,
):
    return DayStatus(
        date=date(2025, 1, 1),
        day_type=day_type,
        presence=presence,
        is_late=is_late,
        arrived_after_cutoff=arrived_after_cutoff,
        was_corrected=False,
        checkout_state=checkout_state,
        worked_on_non_working_day=False,
        effective_check_in=None,
        effective_check_out=None,
        counts_in_denominator=counts_in_denominator,
        counts_as_present=counts_as_present,
        label="",
    )


def test_summarize_empty():
    summary = summarize([])
    assert summary.eligible_days == 0
    assert summary.percentage is None


def test_summarize_basic():
    statuses = [
        make_status(presence=Presence.PRESENT),
        make_status(presence=Presence.PRESENT, is_late=True),
        make_status(
            presence=Presence.ABSENT,
            counts_in_denominator=True,
            counts_as_present=False,
        ),
        make_status(
            day_type=DayType.WEEKLY_OFF,
            presence=Presence.NOT_APPLICABLE,
            counts_in_denominator=False,
            counts_as_present=False,
        ),
    ]
    summary = summarize(statuses)
    assert summary.eligible_days == 3
    assert summary.present_days == 2
    assert summary.absent_days == 1
    assert summary.late_days == 1
    assert round(summary.percentage, 1) == round((2 / 3) * 100, 1)


def test_summarize_leave():
    statuses = [
        make_status(
            day_type=DayType.APPROVED_LEAVE,
            presence=Presence.NOT_APPLICABLE,
            counts_in_denominator=False,
            counts_as_present=False,
        )
    ]
    summary = summarize(statuses)
    assert summary.leave_days == 1
    assert summary.eligible_days == 0


# ---------------------------------------------------------------------------
# check_in / check_out
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_check_in_success(member, schedule, policy):
    """First check-in of the day succeeds."""
    frozen_dt = ist(2025, 1, 6, 9, 35)
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_in(member)
    assert result.success is True
    assert result.record is not None
    assert AttendanceRecord.objects.filter(user=member, work_date=date(2025, 1, 6)).exists()


@pytest.mark.django_db
def test_check_in_duplicate(member, schedule, policy):
    """Second check-in on same day returns success=False."""
    frozen_dt = ist(2025, 1, 6, 9, 35)
    with time_machine.travel(frozen_dt, tick=False):
        services.check_in(member)
        result = services.check_in(member)
    assert result.success is False
    assert "Already checked in" in result.message


@pytest.mark.django_db
def test_check_in_no_schedule(member, policy):
    """No schedule configured → graceful failure."""
    frozen_dt = ist(2025, 1, 6, 9, 35)
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_in(member)
    assert result.success is False
    assert "No schedule" in result.message


@pytest.mark.django_db
def test_check_in_non_tracking_user_raises(admin_user):
    """Admin (tracks_attendance=False) → PermissionDenied."""
    with pytest.raises(PermissionDenied):
        services.check_in(admin_user)


@pytest.mark.django_db
def test_check_in_too_early(member, schedule, policy):
    """Check-in more than CHECKIN_EARLY_MINUTES before start → failure."""
    # Schedule starts 9:30; CHECKIN_EARLY_MINUTES=120 means earliest at 7:30
    frozen_dt = ist(2025, 1, 6, 7, 0)  # 7:00 — too early
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_in(member)
    assert result.success is False
    assert "opens at" in result.message


@pytest.mark.django_db
def test_check_in_after_workday_end(member, schedule, policy):
    """Check-in after schedule end time → failure."""
    frozen_dt = ist(2025, 1, 6, 19, 0)  # After 18:30
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_in(member)
    assert result.success is False
    assert "ended" in result.message


@pytest.mark.django_db
def test_check_out_success(member, schedule, policy):
    """Normal check-out after check-in succeeds."""
    d = date(2025, 1, 6)
    check_in_dt = ist(2025, 1, 6, 9, 35)
    AttendanceRecord.objects.create(
        user=member, work_date=d, schedule=schedule, check_in_at=check_in_dt
    )
    frozen_dt = ist(2025, 1, 6, 18, 0)
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_out(member)
    assert result.success is True
    result.record.refresh_from_db()
    assert result.record.check_out_at is not None


@pytest.mark.django_db
def test_check_out_without_check_in(member, schedule, policy):
    """check_out without prior check_in → failure."""
    frozen_dt = ist(2025, 1, 6, 18, 0)
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_out(member)
    assert result.success is False


@pytest.mark.django_db
def test_check_out_duplicate(member, schedule, policy):
    """Second check-out → failure."""
    d = date(2025, 1, 6)
    check_in_dt = ist(2025, 1, 6, 9, 35)
    check_out_dt = ist(2025, 1, 6, 18, 0)
    AttendanceRecord.objects.create(
        user=member, work_date=d, schedule=schedule,
        check_in_at=check_in_dt, check_out_at=check_out_dt,
    )
    frozen_dt = ist(2025, 1, 6, 18, 30)
    with time_machine.travel(frozen_dt, tick=False):
        result = services.check_out(member)
    assert result.success is False
    assert "Already checked out" in result.message


# ---------------------------------------------------------------------------
# submit_correction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_correction_check_in(member, schedule, policy):
    """Submit a check-in correction for a recent past date."""
    d = date(2025, 1, 6)
    # today is Jan 7
    now = ist(2025, 1, 7, 10, 0)
    with time_machine.travel(now, tick=False):
        req = services.submit_correction(
            user=member,
            work_date=d,
            correction_type=CorrectionType.CHECK_IN,
            requested_time=time(9, 30),
            reason="Forgot to check in",
        )
    assert req.pk is not None
    assert req.status == CorrectionStatus.PENDING
    assert req.type == CorrectionType.CHECK_IN


@pytest.mark.django_db
def test_submit_correction_future_date_raises(member, schedule, policy):
    now = ist(2025, 1, 6, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="future"):
            services.submit_correction(
                user=member,
                work_date=date(2025, 1, 7),
                correction_type=CorrectionType.CHECK_IN,
                requested_time=time(9, 30),
                reason="future",
            )


@pytest.mark.django_db
def test_submit_correction_outside_window_raises(member, schedule, policy):
    """Corrections > CORRECTION_WINDOW_DAYS old are rejected."""
    d = date(2024, 1, 1)  # way in the past
    now = ist(2025, 1, 6, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="within"):
            services.submit_correction(
                user=member,
                work_date=d,
                correction_type=CorrectionType.CHECK_IN,
                requested_time=time(9, 30),
                reason="old",
            )


@pytest.mark.django_db
def test_submit_correction_empty_reason_raises(member, schedule, policy):
    d = date(2025, 1, 6)
    now = ist(2025, 1, 7, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="reason"):
            services.submit_correction(
                user=member,
                work_date=d,
                correction_type=CorrectionType.CHECK_IN,
                requested_time=time(9, 30),
                reason="   ",
            )


@pytest.mark.django_db
def test_submit_correction_duplicate_pending_raises(member, schedule, policy):
    d = date(2025, 1, 6)
    now = ist(2025, 1, 7, 10, 0)
    with time_machine.travel(now, tick=False):
        services.submit_correction(
            user=member,
            work_date=d,
            correction_type=CorrectionType.CHECK_IN,
            requested_time=time(9, 30),
            reason="First request",
        )
        with pytest.raises(ValidationError, match="pending correction"):
            services.submit_correction(
                user=member,
                work_date=d,
                correction_type=CorrectionType.CHECK_IN,
                requested_time=time(9, 45),
                reason="Second request",
            )


@pytest.mark.django_db
def test_submit_correction_checkout_without_checkin_raises(member, schedule, policy):
    """Can't request check-out correction if no check-in exists."""
    d = date(2025, 1, 6)
    now = ist(2025, 1, 7, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="without an existing check-in"):
            services.submit_correction(
                user=member,
                work_date=d,
                correction_type=CorrectionType.CHECK_OUT,
                requested_time=time(18, 0),
                reason="Missing checkout",
            )


# ---------------------------------------------------------------------------
# review_correction
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_correction(member, schedule, policy):
    """A pending check-in correction for 2025-01-06."""
    d = date(2025, 1, 6)
    now = ist(2025, 1, 7, 10, 0)
    import time_machine as tm
    with tm.travel(now, tick=False):
        return services.submit_correction(
            user=member,
            work_date=d,
            correction_type=CorrectionType.CHECK_IN,
            requested_time=time(9, 30),
            reason="Forgot to check in",
        )


@pytest.mark.django_db
def test_review_correction_approve(pending_correction, admin_user):
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        result = services.review_correction(pending_correction, admin_user, CorrectionStatus.APPROVED)
    assert result.status == CorrectionStatus.APPROVED
    assert result.reviewed_by == admin_user
    # The AttendanceRecord should have corrected_check_in_at set
    record = AttendanceRecord.objects.get(user=pending_correction.user, work_date=pending_correction.work_date)
    assert record.corrected_check_in_at is not None


@pytest.mark.django_db
def test_review_correction_reject_requires_comment(pending_correction, admin_user):
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="comment is required"):
            services.review_correction(
                pending_correction, admin_user, CorrectionStatus.REJECTED, comment=""
            )


@pytest.mark.django_db
def test_review_correction_reject_with_comment(pending_correction, admin_user):
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        result = services.review_correction(
            pending_correction, admin_user, CorrectionStatus.REJECTED, comment="Not valid"
        )
    assert result.status == CorrectionStatus.REJECTED
    assert result.review_comment == "Not valid"


@pytest.mark.django_db
def test_review_correction_non_admin_raises(pending_correction, member):
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(PermissionDenied):
            services.review_correction(pending_correction, member, CorrectionStatus.APPROVED)


@pytest.mark.django_db
def test_review_correction_already_reviewed_raises(pending_correction, admin_user):
    """Reviewing an already-reviewed correction raises ValidationError."""
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        services.review_correction(pending_correction, admin_user, CorrectionStatus.APPROVED)
        pending_correction.refresh_from_db()
        with pytest.raises(ValidationError, match="already been reviewed"):
            services.review_correction(pending_correction, admin_user, CorrectionStatus.APPROVED)


@pytest.mark.django_db
def test_review_correction_invalid_decision_raises(pending_correction, admin_user):
    now = ist(2025, 1, 8, 10, 0)
    with time_machine.travel(now, tick=False):
        with pytest.raises(ValidationError, match="Invalid decision"):
            services.review_correction(pending_correction, admin_user, "maybe")
