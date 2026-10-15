from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),  # POST only
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),
]
