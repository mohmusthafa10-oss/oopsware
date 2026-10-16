from django.contrib import admin
from .models import AttendanceCorrectionRequest, AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("user", "work_date", "check_in_at", "check_out_at", "corrected_check_in_at", "corrected_check_out_at")
    list_filter = ("work_date",)
    search_fields = ("user__email", "user__full_name")
    ordering = ("-work_date",)


@admin.register(AttendanceCorrectionRequest)
class AttendanceCorrectionRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "work_date", "type", "requested_time", "status", "reviewed_by", "created_at")
    list_filter = ("status", "type", "work_date")
    search_fields = ("user__email", "user__full_name", "reason")
    ordering = ("-created_at",)
