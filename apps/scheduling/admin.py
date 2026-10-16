from django.contrib import admin
from .models import CalendarPolicy, Holiday, WorkSchedule


@admin.register(CalendarPolicy)
class CalendarPolicyAdmin(admin.ModelAdmin):
    list_display = ("effective_from", "sunday_off", "second_saturday_off", "created_by", "created_at")
    ordering = ("-effective_from",)


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "kind", "created_by", "created_at")
    list_filter = ("kind",)
    ordering = ("date",)
    search_fields = ("name",)


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "start_time",
        "end_time",
        "late_grace_minutes",
        "absence_cutoff_minutes",
        "effective_from",
        "effective_to",
    )
    list_filter = ("working_weekdays",)
    search_fields = ("user__email", "user__full_name")
    ordering = ("-effective_from",)
