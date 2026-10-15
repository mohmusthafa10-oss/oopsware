from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("manage/", views.AdminDashboardView.as_view(), name="manage_dashboard"),
    path("me/", views.UserDashboardView.as_view(), name="user_dashboard"),
]