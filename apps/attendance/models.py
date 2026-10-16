from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

from apps.scheduling.models import WorkSchedule


class AttendanceRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    work_date = models.DateField(db_index=True)
    schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    corrected_check_in_at = models.DateTimeField(null=True, blank=True)
    corrected_check_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "user"]
        constraints = [
            UniqueConstraint(fields=["user", "work_date"], name="unique_user_work_date"),
            CheckConstraint(
                condition=(
                    (Q(check_out_at__isnull=True) | Q(check_in_at__isnull=True) | Q(check_out_at__gt=F("check_in_at")))
                    & (
                        Q(corrected_check_out_at__isnull=True)
                        | Q(corrected_check_in_at__isnull=True)
                        | Q(corrected_check_out_at__gt=F("corrected_check_in_at"))
                    )
                ),
                name="attendance_checkout_after_checkin",
            ),
        ]

    def __str__(self):
        return f"{self.user.full_name} on {self.work_date}: in={self.effective_check_in}, out={self.effective_check_out}"

    @property
    def effective_check_in(self):
        return self.corrected_check_in_at or self.check_in_at

    @property
    def effective_check_out(self):
        return self.corrected_check_out_at or self.check_out_at

    def clean(self):
        super().clean()
        if hasattr(self, "user") and self.user_id:
            if not getattr(self.user, "tracks_attendance", False):
                raise ValidationError({"user": "Only users who track attendance can have attendance records."})

        eff_in = self.effective_check_in
        eff_out = self.effective_check_out
        if eff_in and eff_out and eff_out <= eff_in:
            raise ValidationError({"check_out_at": "Check-out time must be strictly after check-in time."})


class CorrectionType(models.TextChoices):
    CHECK_IN = "check_in", "Check in"
    CHECK_OUT = "check_out", "Check out"


class CorrectionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceCorrectionRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="correction_requests",
    )
    work_date = models.DateField(db_index=True)
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="correction_requests",
    )
    type = models.CharField(max_length=20, choices=CorrectionType.choices)
    requested_time = models.TimeField()
    reason = models.TextField()
    original_value = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=CorrectionStatus.choices,
        default=CorrectionStatus.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_corrections",
    )
    review_comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["user", "work_date", "type"],
                condition=Q(status="pending"),
                name="unique_pending_correction_per_user_date_type",
            )
        ]

    def __str__(self):
        return f"{self.user.full_name} {self.type} on {self.work_date} ({self.status})"
