from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, F, Func, Q, Value


class CalendarPolicy(models.Model):
    effective_from = models.DateField(unique=True)
    sunday_off = models.BooleanField(default=True)
    second_saturday_off = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_calendar_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]
        verbose_name_plural = "Calendar policies"

    def __str__(self):
        return f"Policy from {self.effective_from} (Sun off: {self.sunday_off}, 2nd Sat off: {self.second_saturday_off})"


class HolidayKind(models.TextChoices):
    HOLIDAY = "holiday", "Holiday"
    WORKING_OVERRIDE = "working_override", "Working override"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=150)
    kind = models.CharField(
        max_length=20,
        choices=HolidayKind.choices,
        default=HolidayKind.HOLIDAY,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_holidays",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date}: {self.name} ({self.get_kind_display()})"


def default_working_weekdays():
    return [0, 1, 2, 3, 4, 5]  # Monday through Saturday


class WorkSchedule(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    start_time = models.TimeField(default=time(9, 30))
    end_time = models.TimeField(default=time(18, 30))
    late_grace_minutes = models.PositiveIntegerField(default=0)
    absence_cutoff_minutes = models.PositiveIntegerField(default=60)
    working_weekdays = ArrayField(
        models.SmallIntegerField(),
        default=default_working_weekdays,
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_work_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="schedule_end_gt_start",
            ),
            CheckConstraint(
                condition=Q(late_grace_minutes__gte=0),
                name="schedule_late_grace_gte_0",
            ),
            CheckConstraint(
                condition=Q(absence_cutoff_minutes__gt=F("late_grace_minutes")),
                name="schedule_cutoff_gt_grace",
            ),
            CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="schedule_effective_to_gte_from",
            ),
            ExclusionConstraint(
                name="exclude_overlapping_schedules",
                expressions=[
                    (
                        Func(
                            F("effective_from"),
                            F("effective_to"),
                            Value("[]"),
                            function="daterange",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                    (F("user"), RangeOperators.EQUAL),
                ],
            ),
        ]

    def __str__(self):
        to_str = str(self.effective_to) if self.effective_to else "present"
        return f"{self.user.full_name}: {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} [{self.effective_from} to {to_str}]"

    def clean(self):
        super().clean()
        if hasattr(self, "user") and self.user_id:
            if not getattr(self.user, "tracks_attendance", False):
                raise ValidationError({"user": "Only users who track attendance can have a work schedule."})

        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError({"end_time": "End time must be after start time (no overnight shifts)."})

        if self.late_grace_minutes is not None and self.late_grace_minutes < 0:
            raise ValidationError({"late_grace_minutes": "Late grace minutes must be non-negative."})

        if self.absence_cutoff_minutes is not None and self.late_grace_minutes is not None:
            if self.absence_cutoff_minutes <= self.late_grace_minutes:
                raise ValidationError(
                    {"absence_cutoff_minutes": "Absence cutoff minutes must be greater than late grace minutes."}
                )

        if self.start_time and self.end_time and self.absence_cutoff_minutes is not None:
            dummy_day = date(2000, 1, 1)
            start_dt = datetime.combine(dummy_day, self.start_time)
            end_dt = datetime.combine(dummy_day, self.end_time)
            if start_dt + timedelta(minutes=self.absence_cutoff_minutes) > end_dt:
                raise ValidationError(
                    {"absence_cutoff_minutes": "Start time plus absence cutoff cannot exceed schedule end time."}
                )

        if self.effective_to and self.effective_from:
            if self.effective_to < self.effective_from:
                raise ValidationError({"effective_to": "effective_to must be on or after effective_from."})

        if not self.working_weekdays:
            raise ValidationError({"working_weekdays": "Working weekdays cannot be empty."})

        seen = set()
        for day in self.working_weekdays:
            if day < 0 or day > 6:
                raise ValidationError({"working_weekdays": f"Invalid weekday {day}; must be 0 (Monday) to 6 (Sunday)."})
            if day in seen:
                raise ValidationError({"working_weekdays": f"Duplicate weekday {day} in working weekdays list."})
            seen.add(day)
