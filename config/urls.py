from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.scheduling.urls")),
    path("", include("apps.attendance.urls")),
]