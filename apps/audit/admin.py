from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_repr")
    list_filter = ("action", "created_at")
    search_fields = ("action", "target_repr", "actor__email")
    readonly_fields = (
        "created_at",
        "actor",
        "action",
        "target_content_type",
        "target_object_id",
        "target_repr",
        "before",
        "after",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
