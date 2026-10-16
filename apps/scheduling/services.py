from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit import services as audit_services
from .models import CalendarPolicy, Holiday, WorkSchedule


def create_schedule_version(user, data: dict, actor=None) -> WorkSchedule:
    """Create a new WorkSchedule version for `user`, closing any open schedule."""
    if not getattr(user, "tracks_attendance", False):
        raise ValidationError("Only users who track attendance can have a work schedule.")

    new_effective_from = data.get("effective_from")
    if not new_effective_from:
        raise ValidationError({"effective_from": "Effective from date is required."})

    with transaction.atomic():
        open_sched = (
            WorkSchedule.objects.select_for_update()
            .filter(user=user, effective_to__isnull=True)
            .first()
        )
        before_state = None
        if open_sched:
            if new_effective_from <= open_sched.effective_from:
                raise ValidationError(
                    {"effective_from": "New schedule effective_from must be after the current schedule's start date."}
                )
            before_state = {
                "id": open_sched.id,
                "effective_from": open_sched.effective_from,
                "effective_to": open_sched.effective_to,
            }
            open_sched.effective_to = new_effective_from - timedelta(days=1)
            open_sched.full_clean()
            open_sched.save(update_fields=["effective_to"])

        new_schedule = WorkSchedule(
            user=user,
            start_time=data["start_time"],
            end_time=data["end_time"],
            late_grace_minutes=data.get("late_grace_minutes", 0),
            absence_cutoff_minutes=data.get("absence_cutoff_minutes", 60),
            working_weekdays=data.get("working_weekdays", [0, 1, 2, 3, 4, 5]),
            effective_from=new_effective_from,
            effective_to=data.get("effective_to", None),
            created_by=actor,
        )
        new_schedule.full_clean()
        new_schedule.save()

        audit_services.record(
            actor=actor,
            action=audit_services.SCHEDULE_CREATED,
            target=new_schedule,
            before=before_state,
            after={
                "id": new_schedule.id,
                "user_id": user.id,
                "start_time": new_schedule.start_time,
                "end_time": new_schedule.end_time,
                "late_grace_minutes": new_schedule.late_grace_minutes,
                "absence_cutoff_minutes": new_schedule.absence_cutoff_minutes,
                "working_weekdays": new_schedule.working_weekdays,
                "effective_from": new_schedule.effective_from,
                "effective_to": new_schedule.effective_to,
            },
        )
        return new_schedule


def create_holiday(*, holiday_date: date, name: str, kind: str, actor=None) -> Holiday:
    """Create a new Holiday or working override, audited."""
    with transaction.atomic():
        holiday = Holiday(date=holiday_date, name=name, kind=kind, created_by=actor)
        holiday.full_clean()
        holiday.save()

        audit_services.record(
            actor=actor,
            action=audit_services.HOLIDAY_CREATED,
            target=holiday,
            before=None,
            after={"date": holiday.date, "name": holiday.name, "kind": holiday.kind},
        )
        return holiday


def update_holiday(holiday: Holiday, *, name: str, kind: str, actor=None) -> Holiday:
    """Update an existing Holiday, audited."""
    with transaction.atomic():
        before_state = {"date": holiday.date, "name": holiday.name, "kind": holiday.kind}
        holiday.name = name
        holiday.kind = kind
        holiday.full_clean()
        holiday.save()

        audit_services.record(
            actor=actor,
            action=audit_services.HOLIDAY_UPDATED,
            target=holiday,
            before=before_state,
            after={"date": holiday.date, "name": holiday.name, "kind": holiday.kind},
        )
        return holiday


def delete_holiday(holiday: Holiday, actor=None) -> None:
    """Delete a Holiday, audited."""
    with transaction.atomic():
        before_state = {"date": holiday.date, "name": holiday.name, "kind": holiday.kind}
        audit_services.record(
            actor=actor,
            action=audit_services.HOLIDAY_DELETED,
            target=holiday,
            before=before_state,
            after=None,
        )
        holiday.delete()


def create_calendar_policy(
    *,
    effective_from: date,
    sunday_off: bool = True,
    second_saturday_off: bool = True,
    actor=None,
) -> CalendarPolicy:
    """Create a new CalendarPolicy version, audited."""
    with transaction.atomic():
        policy = CalendarPolicy(
            effective_from=effective_from,
            sunday_off=sunday_off,
            second_saturday_off=second_saturday_off,
            created_by=actor,
        )
        policy.full_clean()
        policy.save()

        audit_services.record(
            actor=actor,
            action=audit_services.CALENDAR_POLICY_CREATED,
            target=policy,
            before=None,
            after={
                "effective_from": policy.effective_from,
                "sunday_off": policy.sunday_off,
                "second_saturday_off": policy.second_saturday_off,
            },
        )
        return policy
