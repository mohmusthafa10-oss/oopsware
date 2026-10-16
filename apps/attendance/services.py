from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.audit import services as audit_services
from apps.core import timeutils
from apps.scheduling import selectors as sched_selectors
from apps.scheduling.models import HolidayKind, WorkSchedule
from .leave_hook import approved_leave_dates
from .models import AttendanceCorrectionRequest, AttendanceRecord, CorrectionStatus, CorrectionType


class DayType:
    WORKING = "WORKING"
    HOLIDAY = "HOLIDAY"
    WEEKLY_OFF = "WEEKLY_OFF"
    SCHEDULED_OFF = "SCHEDULED_OFF"
    APPROVED_LEAVE = "APPROVED_LEAVE"
    FUTURE = "FUTURE"
    NO_SCHEDULE = "NO_SCHEDULE"
    INACTIVE = "INACTIVE"


class Presence:
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NOT_YET = "NOT_YET"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CheckoutState:
    DONE = "DONE"
    PENDING = "PENDING"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class DayStatus:
    date: date
    day_type: str
    presence: str
    is_late: bool
    arrived_after_cutoff: bool
    was_corrected: bool
    checkout_state: str
    worked_on_non_working_day: bool
    effective_check_in: datetime | None
    effective_check_out: datetime | None
    counts_in_denominator: bool
    counts_as_present: bool
    label: str


@dataclass(frozen=True)
class AttendanceSummary:
    eligible_days: int
    present_days: int
    late_days: int
    absent_days: int
    leave_days: int
    missing_checkout_days: int
    percentage: float | None


@dataclass
class ServiceResult:
    success: bool
    message: str
    record: AttendanceRecord | None = None


def resolve_day(user: User, day: date, now: datetime | None = None, leave_dates: set[date] | None = None) -> DayStatus:
    """Evaluate attendance status for `user` on `day` (work date).

    All logic uses IST-aware datetimes. Correctness does not depend on background tasks.
    """
    if now is None:
        now = timeutils.local_now()
    today = timeutils.local_date(now)

    # 1. Future dates are excluded
    if day > today:
        return DayStatus(
            date=day,
            day_type=DayType.FUTURE,
            presence=Presence.NOT_APPLICABLE,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label="Future",
        )

    # 2. Deactivation check
    if user.deactivated_at:
        deact_date = timeutils.local_date(user.deactivated_at)
        if day > deact_date:
            return DayStatus(
                date=day,
                day_type=DayType.INACTIVE,
                presence=Presence.NOT_APPLICABLE,
                is_late=False,
                arrived_after_cutoff=False,
                was_corrected=False,
                checkout_state=CheckoutState.NOT_APPLICABLE,
                worked_on_non_working_day=False,
                effective_check_in=None,
                effective_check_out=None,
                counts_in_denominator=False,
                counts_as_present=False,
                label="Inactive",
            )

    # Schedule check
    first_sched = user.schedules.order_by("effective_from").first()
    if not first_sched or day < first_sched.effective_from:
        return DayStatus(
            date=day,
            day_type=DayType.NO_SCHEDULE,
            presence=Presence.NOT_APPLICABLE,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label="No schedule",
        )

    schedule = sched_selectors.schedule_for(user, day)
    if not schedule:
        return DayStatus(
            date=day,
            day_type=DayType.NO_SCHEDULE,
            presence=Presence.NOT_APPLICABLE,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label="No schedule",
        )

    record = AttendanceRecord.objects.filter(user=user, work_date=day).first()
    has_check_in = bool(record and record.effective_check_in)
    was_corrected = bool(record and (record.corrected_check_in_at or record.corrected_check_out_at))

    # 3. Calendar day type / scheduled weekdays check
    cal_type = sched_selectors.calendar_day_type(day)
    holiday = sched_selectors.Holiday.objects.filter(date=day).first()
    is_override = bool(holiday and holiday.kind == HolidayKind.WORKING_OVERRIDE)

    non_working_type = None
    if not is_override:
        if cal_type == sched_selectors.DayType.HOLIDAY:
            non_working_type = DayType.HOLIDAY
            default_label = "Holiday"
        elif cal_type == sched_selectors.DayType.WEEKLY_OFF:
            non_working_type = DayType.WEEKLY_OFF
            default_label = "Weekly off"
        elif day.weekday() not in schedule.working_weekdays:
            non_working_type = DayType.SCHEDULED_OFF
            default_label = "Scheduled off"

    if non_working_type:
        if has_check_in:
            chk_state = (
                CheckoutState.DONE
                if record.effective_check_out
                else (CheckoutState.PENDING if day == today else CheckoutState.MISSING)
            )
            return DayStatus(
                date=day,
                day_type=non_working_type,
                presence=Presence.PRESENT,
                is_late=False,
                arrived_after_cutoff=False,
                was_corrected=was_corrected,
                checkout_state=chk_state,
                worked_on_non_working_day=True,
                effective_check_in=record.effective_check_in,
                effective_check_out=record.effective_check_out,
                counts_in_denominator=False,
                counts_as_present=False,
                label=f"Worked ({default_label})",
            )
        return DayStatus(
            date=day,
            day_type=non_working_type,
            presence=Presence.NOT_APPLICABLE,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label=default_label,
        )

    # 4. Approved leave check
    user_leaves = leave_dates if leave_dates is not None else approved_leave_dates([user.id], day, day).get(user.id, set())
    if day in user_leaves:
        if has_check_in:
            chk_state = (
                CheckoutState.DONE
                if record.effective_check_out
                else (CheckoutState.PENDING if day == today else CheckoutState.MISSING)
            )
            return DayStatus(
                date=day,
                day_type=DayType.APPROVED_LEAVE,
                presence=Presence.PRESENT,
                is_late=False,
                arrived_after_cutoff=False,
                was_corrected=was_corrected,
                checkout_state=chk_state,
                worked_on_non_working_day=True,
                effective_check_in=record.effective_check_in,
                effective_check_out=record.effective_check_out,
                counts_in_denominator=False,
                counts_as_present=False,
                label="Present (on leave)",
            )
        return DayStatus(
            date=day,
            day_type=DayType.APPROVED_LEAVE,
            presence=Presence.NOT_APPLICABLE,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label="Approved leave",
        )

    # 5. Eligible working day
    sched_start = timeutils.make_aware_local(day, schedule.start_time)
    grace_dt = sched_start + timedelta(minutes=schedule.late_grace_minutes)
    cutoff_dt = sched_start + timedelta(minutes=schedule.absence_cutoff_minutes)
    sched_end = timeutils.make_aware_local(day, schedule.end_time)

    if has_check_in:
        eff_in = record.effective_check_in
        is_late = eff_in > grace_dt
        arrived_after_cutoff = eff_in >= cutoff_dt

        if record.effective_check_out:
            checkout_state = CheckoutState.DONE
        elif day == today:
            checkout_state = CheckoutState.PENDING
        else:
            checkout_state = CheckoutState.MISSING

        if arrived_after_cutoff:
            label = "Present - After Cutoff"
        elif is_late:
            label = "Present - Late"
        elif checkout_state == CheckoutState.MISSING:
            label = "Missing checkout"
        elif checkout_state == CheckoutState.PENDING and now > sched_end:
            label = "Checkout pending"
        else:
            label = "Present"

        return DayStatus(
            date=day,
            day_type=DayType.WORKING,
            presence=Presence.PRESENT,
            is_late=is_late,
            arrived_after_cutoff=arrived_after_cutoff,
            was_corrected=was_corrected,
            checkout_state=checkout_state,
            worked_on_non_working_day=False,
            effective_check_in=record.effective_check_in,
            effective_check_out=record.effective_check_out,
            counts_in_denominator=True,
            counts_as_present=True,
            label=label,
        )

    # No check-in
    # BOUNDARY RULE:
    # A valid on-time check-in must occur strictly before the cutoff instant.
    # At or after the cutoff instant, no check-in means absent.
    if now < cutoff_dt:
        return DayStatus(
            date=day,
            day_type=DayType.WORKING,
            presence=Presence.NOT_YET,
            is_late=False,
            arrived_after_cutoff=False,
            was_corrected=False,
            checkout_state=CheckoutState.NOT_APPLICABLE,
            worked_on_non_working_day=False,
            effective_check_in=None,
            effective_check_out=None,
            counts_in_denominator=False,
            counts_as_present=False,
            label="Not checked in",
        )

    return DayStatus(
        date=day,
        day_type=DayType.WORKING,
        presence=Presence.ABSENT,
        is_late=False,
        arrived_after_cutoff=False,
        was_corrected=False,
        checkout_state=CheckoutState.NOT_APPLICABLE,
        worked_on_non_working_day=False,
        effective_check_in=None,
        effective_check_out=None,
        counts_in_denominator=True,
        counts_as_present=False,
        label="Absent",
    )


def summarize(statuses: list[DayStatus]) -> AttendanceSummary:
    """Compute aggregate attendance metrics from a list of DayStatus objects."""
    eligible_days = sum(1 for s in statuses if s.counts_in_denominator)
    present_days = sum(1 for s in statuses if s.counts_as_present)
    late_days = sum(1 for s in statuses if s.is_late and s.counts_as_present)
    absent_days = sum(1 for s in statuses if s.presence == Presence.ABSENT)
    leave_days = sum(1 for s in statuses if s.day_type == DayType.APPROVED_LEAVE)
    missing_checkout_days = sum(1 for s in statuses if s.checkout_state == CheckoutState.MISSING)

    percentage = None
    if eligible_days > 0:
        percentage = round((present_days / eligible_days) * 100, 1)

    return AttendanceSummary(
        eligible_days=eligible_days,
        present_days=present_days,
        late_days=late_days,
        absent_days=absent_days,
        leave_days=leave_days,
        missing_checkout_days=missing_checkout_days,
        percentage=percentage,
    )


def resolve_range(
    users,
    start: date,
    end: date,
    now: datetime | None = None,
    leave_dates: dict[int, set[date]] | None = None,
) -> dict[User, list[DayStatus]]:
    """Resolve attendance status for multiple users across a date range in O(1) database queries."""
    if now is None:
        now = timeutils.local_now()
    today = timeutils.local_date(now)

    user_list = list(users)
    user_ids = [u.id for u in user_list]

    # Preload 1: Holidays
    holidays_map = sched_selectors.get_holidays_map(start, end)
    # Preload 2: Policies
    policies_list = sched_selectors.get_calendar_policies_list()
    # Preload 3: Schedules
    schedules_by_user = sched_selectors.get_schedules_map(user_ids, start, end)
    # Preload 4: Attendance Records
    records_qs = AttendanceRecord.objects.filter(
        user_id__in=user_ids,
        work_date__gte=start,
        work_date__lte=end,
    )
    records_by_user_date: dict[tuple[int, date], AttendanceRecord] = {
        (r.user_id, r.work_date): r for r in records_qs
    }
    # Preload 5: Approved Leave
    leave_by_user = (
        leave_dates
        if leave_dates is not None
        else approved_leave_dates(user_ids, start, end)
    )

    days_in_range = []
    curr = start
    while curr <= end:
        days_in_range.append(curr)
        curr += timedelta(days=1)

    result: dict[User, list[DayStatus]] = {}

    for user in user_list:
        user_statuses = []
        user_leaves = leave_by_user.get(user.id, set())
        user_scheds = schedules_by_user.get(user.id, [])
        first_sched_date = user_scheds[0].effective_from if user_scheds else None
        deact_date = timeutils.local_date(user.deactivated_at) if user.deactivated_at else None

        for day in days_in_range:
            # 1. Future
            if day > today:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.FUTURE,
                        presence=Presence.NOT_APPLICABLE,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=False,
                        counts_as_present=False,
                        label="Future",
                    )
                )
                continue

            # 2. Deactivation / No schedule
            if deact_date and day > deact_date:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.INACTIVE,
                        presence=Presence.NOT_APPLICABLE,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=False,
                        counts_as_present=False,
                        label="Inactive",
                    )
                )
                continue

            if not first_sched_date or day < first_sched_date:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.NO_SCHEDULE,
                        presence=Presence.NOT_APPLICABLE,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=False,
                        counts_as_present=False,
                        label="No schedule",
                    )
                )
                continue

            schedule = sched_selectors.schedule_for_user_from_cache(user.id, day, schedules_by_user)
            if not schedule:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.NO_SCHEDULE,
                        presence=Presence.NOT_APPLICABLE,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=False,
                        counts_as_present=False,
                        label="No schedule",
                    )
                )
                continue

            record = records_by_user_date.get((user.id, day))
            has_check_in = bool(record and record.effective_check_in)
            was_corrected = bool(record and (record.corrected_check_in_at or record.corrected_check_out_at))

            # 3. Calendar check
            cal_type, is_override = sched_selectors.calendar_day_type_from_cache(
                day, holidays_map, policies_list
            )
            non_working_type = None
            if not is_override:
                if cal_type == sched_selectors.DayType.HOLIDAY:
                    non_working_type = DayType.HOLIDAY
                    default_label = "Holiday"
                elif cal_type == sched_selectors.DayType.WEEKLY_OFF:
                    non_working_type = DayType.WEEKLY_OFF
                    default_label = "Weekly off"
                elif day.weekday() not in schedule.working_weekdays:
                    non_working_type = DayType.SCHEDULED_OFF
                    default_label = "Scheduled off"

            if non_working_type:
                if has_check_in:
                    chk_state = (
                        CheckoutState.DONE
                        if record.effective_check_out
                        else (CheckoutState.PENDING if day == today else CheckoutState.MISSING)
                    )
                    user_statuses.append(
                        DayStatus(
                            date=day,
                            day_type=non_working_type,
                            presence=Presence.PRESENT,
                            is_late=False,
                            arrived_after_cutoff=False,
                            was_corrected=was_corrected,
                            checkout_state=chk_state,
                            worked_on_non_working_day=True,
                            effective_check_in=record.effective_check_in,
                            effective_check_out=record.effective_check_out,
                            counts_in_denominator=False,
                            counts_as_present=False,
                            label=f"Worked ({default_label})",
                        )
                    )
                else:
                    user_statuses.append(
                        DayStatus(
                            date=day,
                            day_type=non_working_type,
                            presence=Presence.NOT_APPLICABLE,
                            is_late=False,
                            arrived_after_cutoff=False,
                            was_corrected=False,
                            checkout_state=CheckoutState.NOT_APPLICABLE,
                            worked_on_non_working_day=False,
                            effective_check_in=None,
                            effective_check_out=None,
                            counts_in_denominator=False,
                            counts_as_present=False,
                            label=default_label,
                        )
                    )
                continue

            # 4. Leave
            if day in user_leaves:
                if has_check_in:
                    chk_state = (
                        CheckoutState.DONE
                        if record.effective_check_out
                        else (CheckoutState.PENDING if day == today else CheckoutState.MISSING)
                    )
                    user_statuses.append(
                        DayStatus(
                            date=day,
                            day_type=DayType.APPROVED_LEAVE,
                            presence=Presence.PRESENT,
                            is_late=False,
                            arrived_after_cutoff=False,
                            was_corrected=was_corrected,
                            checkout_state=chk_state,
                            worked_on_non_working_day=True,
                            effective_check_in=record.effective_check_in,
                            effective_check_out=record.effective_check_out,
                            counts_in_denominator=False,
                            counts_as_present=False,
                            label="Present (on leave)",
                        )
                    )
                else:
                    user_statuses.append(
                        DayStatus(
                            date=day,
                            day_type=DayType.APPROVED_LEAVE,
                            presence=Presence.NOT_APPLICABLE,
                            is_late=False,
                            arrived_after_cutoff=False,
                            was_corrected=False,
                            checkout_state=CheckoutState.NOT_APPLICABLE,
                            worked_on_non_working_day=False,
                            effective_check_in=None,
                            effective_check_out=None,
                            counts_in_denominator=False,
                            counts_as_present=False,
                            label="Approved leave",
                        )
                    )
                continue

            # 5. Eligible working day
            sched_start = timeutils.make_aware_local(day, schedule.start_time)
            grace_dt = sched_start + timedelta(minutes=schedule.late_grace_minutes)
            cutoff_dt = sched_start + timedelta(minutes=schedule.absence_cutoff_minutes)
            sched_end = timeutils.make_aware_local(day, schedule.end_time)

            if has_check_in:
                eff_in = record.effective_check_in
                is_late = eff_in > grace_dt
                arrived_after_cutoff = eff_in >= cutoff_dt

                if record.effective_check_out:
                    checkout_state = CheckoutState.DONE
                elif day == today:
                    checkout_state = CheckoutState.PENDING
                else:
                    checkout_state = CheckoutState.MISSING

                if arrived_after_cutoff:
                    label = "Present - After Cutoff"
                elif is_late:
                    label = "Present - Late"
                elif checkout_state == CheckoutState.MISSING:
                    label = "Missing checkout"
                elif checkout_state == CheckoutState.PENDING and now > sched_end:
                    label = "Checkout pending"
                else:
                    label = "Present"

                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.WORKING,
                        presence=Presence.PRESENT,
                        is_late=is_late,
                        arrived_after_cutoff=arrived_after_cutoff,
                        was_corrected=was_corrected,
                        checkout_state=checkout_state,
                        worked_on_non_working_day=False,
                        effective_check_in=record.effective_check_in,
                        effective_check_out=record.effective_check_out,
                        counts_in_denominator=True,
                        counts_as_present=True,
                        label=label,
                    )
                )
                continue

            # No check-in
            if now < cutoff_dt:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.WORKING,
                        presence=Presence.NOT_YET,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=False,
                        counts_as_present=False,
                        label="Not checked in",
                    )
                )
            else:
                user_statuses.append(
                    DayStatus(
                        date=day,
                        day_type=DayType.WORKING,
                        presence=Presence.ABSENT,
                        is_late=False,
                        arrived_after_cutoff=False,
                        was_corrected=False,
                        checkout_state=CheckoutState.NOT_APPLICABLE,
                        worked_on_non_working_day=False,
                        effective_check_in=None,
                        effective_check_out=None,
                        counts_in_denominator=True,
                        counts_as_present=False,
                        label="Absent",
                    )
                )

        result[user] = user_statuses

    return result


def check_in(user: User) -> ServiceResult:
    """Record a member check-in using server time only."""
    if not getattr(user, "tracks_attendance", False):
        raise PermissionDenied("Only members track attendance.")

    now = timeutils.local_now()
    work_date = timeutils.local_date(now)

    schedule = sched_selectors.schedule_for(user, work_date)
    if not schedule:
        return ServiceResult(
            success=False,
            message="No schedule is configured for you. Contact your administrator.",
        )

    # Time window validation
    start_dt = timeutils.make_aware_local(work_date, schedule.start_time)
    end_dt = timeutils.make_aware_local(work_date, schedule.end_time)
    early_limit = start_dt - timedelta(minutes=settings.CHECKIN_EARLY_MINUTES)

    is_working_day = sched_selectors.is_scheduled_working_day(user, work_date)
    if is_working_day:
        if now < early_limit:
            return ServiceResult(
                success=False,
                message=f"Check-in opens at {schedule.start_time.strftime('%H:%M')} (up to {settings.CHECKIN_EARLY_MINUTES} minutes early).",
            )
        if now > end_dt:
            return ServiceResult(
                success=False,
                message="Workday has ended. Please submit an attendance correction request.",
            )

    with transaction.atomic():
        record, created = AttendanceRecord.objects.get_or_create(
            user=user,
            work_date=work_date,
            defaults={"schedule": schedule, "check_in_at": now},
        )
        if not created:
            return ServiceResult(
                success=False,
                message="Already checked in today.",
                record=record,
            )

        return ServiceResult(
            success=True,
            message="Checked in successfully.",
            record=record,
        )


def check_out(user: User) -> ServiceResult:
    """Record a member check-out using server time only."""
    if not getattr(user, "tracks_attendance", False):
        raise PermissionDenied("Only members track attendance.")

    now = timeutils.local_now()
    work_date = timeutils.local_date(now)

    with transaction.atomic():
        record = (
            AttendanceRecord.objects.select_for_update()
            .filter(user=user, work_date=work_date)
            .first()
        )
        if not record or not record.check_in_at:
            return ServiceResult(
                success=False,
                message="No check-in record found for today.",
            )

        if record.check_out_at or record.corrected_check_out_at:
            return ServiceResult(
                success=False,
                message="Already checked out today.",
                record=record,
            )

        record.check_out_at = now
        record.save(update_fields=["check_out_at", "updated_at"])
        return ServiceResult(
            success=True,
            message="Checked out successfully.",
            record=record,
        )


def submit_correction(
    user: User,
    work_date: date,
    correction_type: str,
    requested_time: time,
    reason: str,
) -> AttendanceCorrectionRequest:
    """Submit an attendance correction request for a past or current work date."""
    if not getattr(user, "tracks_attendance", False):
        raise PermissionDenied("Only members track attendance.")

    today = timeutils.local_date()
    if work_date > today:
        raise ValidationError("Correction cannot be requested for a future date.")

    if (today - work_date).days > settings.CORRECTION_WINDOW_DAYS:
        raise ValidationError(
            f"Corrections must be submitted within {settings.CORRECTION_WINDOW_DAYS} days."
        )

    if not reason or not reason.strip():
        raise ValidationError("A reason is required.")

    schedule = sched_selectors.schedule_for(user, work_date)
    if not schedule:
        raise ValidationError("No schedule found for this date.")

    if AttendanceCorrectionRequest.objects.filter(
        user=user, work_date=work_date, type=correction_type, status=CorrectionStatus.PENDING
    ).exists():
        raise ValidationError(
            "A pending correction request already exists for this date and type."
        )

    record = AttendanceRecord.objects.filter(user=user, work_date=work_date).first()

    if correction_type == CorrectionType.CHECK_IN:
        if record and record.effective_check_in:
            raise ValidationError("A check-in already exists for this date.")
        requested_dt = timeutils.make_aware_local(work_date, requested_time)
        end_dt = timeutils.make_aware_local(work_date, schedule.end_time)
        if requested_dt > end_dt:
            raise ValidationError("Requested check-in time cannot be after the schedule end time.")

    elif correction_type == CorrectionType.CHECK_OUT:
        if not record or not record.effective_check_in:
            raise ValidationError("Cannot request check-out correction without an existing check-in.")
        if record.effective_check_out:
            raise ValidationError("A check-out already exists for this date.")
        requested_dt = timeutils.make_aware_local(work_date, requested_time)
        if requested_dt <= record.effective_check_in:
            raise ValidationError("Requested check-out time must be after check-in.")

    original_snapshot = {
        "check_in_at": record.check_in_at.isoformat() if record and record.check_in_at else None,
        "check_out_at": record.check_out_at.isoformat() if record and record.check_out_at else None,
        "corrected_check_in_at": record.corrected_check_in_at.isoformat() if record and record.corrected_check_in_at else None,
        "corrected_check_out_at": record.corrected_check_out_at.isoformat() if record and record.corrected_check_out_at else None,
    }

    req = AttendanceCorrectionRequest(
        user=user,
        work_date=work_date,
        record=record,
        type=correction_type,
        requested_time=requested_time,
        reason=reason.strip(),
        original_value=original_snapshot,
    )
    req.full_clean()
    req.save()
    return req


def review_correction(
    request_obj: AttendanceCorrectionRequest,
    reviewer: User,
    decision: str,
    comment: str = "",
) -> AttendanceCorrectionRequest:
    """Review and either approve or reject an attendance correction request."""
    if not getattr(reviewer, "is_admin", False):
        raise PermissionDenied("Only admins can review correction requests.")

    with transaction.atomic():
        req = (
            AttendanceCorrectionRequest.objects.select_for_update()
            .select_related("user")
            .get(pk=request_obj.pk)
        )
        if req.status != CorrectionStatus.PENDING:
            raise ValidationError("This correction request has already been reviewed.")

        now = timeutils.local_now()

        if decision == CorrectionStatus.REJECTED:
            if not comment or not comment.strip():
                raise ValidationError("A comment is required when rejecting a request.")
            before_state = {"status": req.status}
            req.status = CorrectionStatus.REJECTED
            req.reviewed_by = reviewer
            req.review_comment = comment.strip()
            req.reviewed_at = now
            req.full_clean()
            req.save()

            audit_services.record(
                actor=reviewer,
                action=audit_services.CORRECTION_REJECTED,
                target=req,
                before=before_state,
                after={"status": req.status, "review_comment": req.review_comment},
            )
            return req

        if decision == CorrectionStatus.APPROVED:
            req_dt = timeutils.make_aware_local(req.work_date, req.requested_time)
            schedule = sched_selectors.schedule_for(req.user, req.work_date)
            if not schedule:
                raise ValidationError("Cannot approve correction: no schedule found for user on that date.")

            record, _ = AttendanceRecord.objects.get_or_create(
                user=req.user,
                work_date=req.work_date,
                defaults={"schedule": schedule},
            )

            before_state = {
                "status": req.status,
                "corrected_check_in_at": record.corrected_check_in_at.isoformat() if record.corrected_check_in_at else None,
                "corrected_check_out_at": record.corrected_check_out_at.isoformat() if record.corrected_check_out_at else None,
            }

            if req.type == CorrectionType.CHECK_IN:
                record.corrected_check_in_at = req_dt
            elif req.type == CorrectionType.CHECK_OUT:
                record.corrected_check_out_at = req_dt

            record.full_clean()
            record.save()

            req.status = CorrectionStatus.APPROVED
            req.reviewed_by = reviewer
            req.review_comment = comment.strip() if comment else ""
            req.reviewed_at = now
            req.record = record
            req.full_clean()
            req.save()

            after_state = {
                "status": req.status,
                "corrected_check_in_at": record.corrected_check_in_at.isoformat() if record.corrected_check_in_at else None,
                "corrected_check_out_at": record.corrected_check_out_at.isoformat() if record.corrected_check_out_at else None,
            }

            audit_services.record(
                actor=reviewer,
                action=audit_services.CORRECTION_APPROVED,
                target=req,
                before=before_state,
                after=after_state,
            )
            return req

        raise ValidationError(f"Invalid decision '{decision}'. Must be approved or rejected.")
