from datetime import date
from django.db.models import Q
from .models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule


class DayType:
    WORKING = "WORKING"
    HOLIDAY = "HOLIDAY"
    WEEKLY_OFF = "WEEKLY_OFF"
    SCHEDULED_OFF = "SCHEDULED_OFF"
    APPROVED_LEAVE = "APPROVED_LEAVE"
    FUTURE = "FUTURE"
    NO_SCHEDULE = "NO_SCHEDULE"
    INACTIVE = "INACTIVE"


def is_second_saturday(d: date) -> bool:
    """Return True if `d` is a Saturday and its day-of-month is between 8 and 14 inclusive."""
    return d.weekday() == 5 and 8 <= d.day <= 14


def get_policy_for_date(d: date) -> CalendarPolicy | None:
    """Return the CalendarPolicy in effect on date `d` (greatest effective_from <= d)."""
    return (
        CalendarPolicy.objects.filter(effective_from__lte=d)
        .order_by("-effective_from")
        .first()
    )


def calendar_day_type(d: date) -> str:
    """Determine calendar day type for date `d`:

    Order of precedence:
    1. Holiday row (holiday -> HOLIDAY, working_override -> WORKING)
    2. CalendarPolicy for `d` (Sunday off -> WEEKLY_OFF, 2nd Saturday off -> WEEKLY_OFF)
    3. Otherwise WORKING.
    """
    holiday = Holiday.objects.filter(date=d).first()
    if holiday:
        if holiday.kind == HolidayKind.WORKING_OVERRIDE:
            return DayType.WORKING
        return DayType.HOLIDAY

    policy = get_policy_for_date(d)
    if policy:
        if d.weekday() == 6 and policy.sunday_off:
            return DayType.WEEKLY_OFF
        if is_second_saturday(d) and policy.second_saturday_off:
            return DayType.WEEKLY_OFF

    return DayType.WORKING


def schedule_for(user, d: date) -> WorkSchedule | None:
    """Return the active WorkSchedule for `user` on date `d` (if any)."""
    if not getattr(user, "tracks_attendance", False):
        return None
    return (
        WorkSchedule.objects.filter(user=user, effective_from__lte=d)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=d))
        .first()
    )


def is_scheduled_working_day(user, d: date) -> bool:
    """Return True if `d` is an active working day for `user` under their schedule."""
    schedule = schedule_for(user, d)
    if not schedule:
        return False

    holiday = Holiday.objects.filter(date=d).first()
    if holiday and holiday.kind == HolidayKind.WORKING_OVERRIDE:
        return True

    if calendar_day_type(d) != DayType.WORKING:
        return False

    return d.weekday() in schedule.working_weekdays


# --- Batch variants for resolve_range (no N+1 queries) ---------------------


def get_holidays_map(start: date, end: date) -> dict[date, Holiday]:
    """Preload all holidays in [start, end] into a date -> Holiday dict."""
    return {h.date: h for h in Holiday.objects.filter(date__gte=start, date__lte=end)}


def get_calendar_policies_list() -> list[CalendarPolicy]:
    """Preload all CalendarPolicy rows ordered by effective_from descending."""
    return list(CalendarPolicy.objects.order_by("-effective_from"))


def calendar_day_type_from_cache(
    d: date,
    holidays_map: dict[date, Holiday],
    policies_list: list[CalendarPolicy],
) -> tuple[str, bool]:
    """Return (day_type, is_working_override) using preloaded holidays and policies."""
    holiday = holidays_map.get(d)
    if holiday:
        if holiday.kind == HolidayKind.WORKING_OVERRIDE:
            return DayType.WORKING, True
        return DayType.HOLIDAY, False

    for policy in policies_list:
        if policy.effective_from <= d:
            if d.weekday() == 6 and policy.sunday_off:
                return DayType.WEEKLY_OFF, False
            if is_second_saturday(d) and policy.second_saturday_off:
                return DayType.WEEKLY_OFF, False
            break

    return DayType.WORKING, False


def get_schedules_map(users, start: date, end: date) -> dict[int, list[WorkSchedule]]:
    """Preload WorkSchedules for `users` covering any part of [start, end].

    Returns a dict mapping user_id -> list of WorkSchedules sorted by effective_from.
    """
    user_ids = [u.id if hasattr(u, "id") else u for u in users]
    qs = (
        WorkSchedule.objects.filter(
            user_id__in=user_ids,
            effective_from__lte=end,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=start))
        .order_by("user_id", "effective_from")
    )
    schedules_by_user = {uid: [] for uid in user_ids}
    for s in qs:
        schedules_by_user[s.user_id].append(s)
    return schedules_by_user


def schedule_for_user_from_cache(
    user_id: int, d: date, schedules_by_user: dict[int, list[WorkSchedule]]
) -> WorkSchedule | None:
    """Find the schedule in force on date `d` from preloaded list."""
    for s in schedules_by_user.get(user_id, []):
        if s.effective_from <= d and (s.effective_to is None or s.effective_to >= d):
            return s
    return None
