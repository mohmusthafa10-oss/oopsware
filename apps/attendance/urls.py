from django.urls import path
from . import views

urlpatterns = [
    # Member attendance & actions
    path("me/check-in/", views.UserCheckInView.as_view(), name="user_check_in"),
    path("me/check-out/", views.UserCheckOutView.as_view(), name="user_check_out"),
    path("me/attendance/", views.UserAttendanceView.as_view(), name="user_attendance"),
    path("me/corrections/", views.UserCorrectionsView.as_view(), name="user_corrections"),

    # Admin attendance dashboard & reviews
    path("manage/attendance/", views.AdminAttendanceView.as_view(), name="manage_attendance"),
    path("manage/attendance/corrections/<int:pk>/review/", views.AdminReviewCorrectionView.as_view(), name="manage_review_correction"),
]
