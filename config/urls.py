from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django's built-in admin is for superuser data maintenance only.
    # The product's admin UI lives under /manage/.
    path("django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
]