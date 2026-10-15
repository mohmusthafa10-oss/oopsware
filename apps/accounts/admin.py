from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import User

admin.site.site_header = "Oopsware data admin"
admin.site.site_title = "Oopsware"


class UserCreationAdminForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name", "role")


class UserChangeAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationAdminForm
    form = UserChangeAdminForm
    ordering = ("full_name",)
    list_display = ("full_name", "email", "role", "is_active", "must_change_password")
    list_filter = ("role", "is_active")
    search_fields = ("full_name", "email")
    readonly_fields = ("last_login", "created_at")
    filter_horizontal = ("groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "role", "is_active", "must_change_password")}),
        ("Django admin access", {"fields": ("is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {"classes": ("wide",), "fields": ("email", "full_name", "role", "password1", "password2")},
        ),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.must_change_password = True  # new accounts must set their own password
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead; history must stay intact