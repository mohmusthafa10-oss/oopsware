from django.urls import path
from . import views

urlpatterns = [
    # Members management
    path("manage/members/", views.MembersListView.as_view(), name="manage_members"),
    path("manage/members/<int:pk>/", views.MemberDetailView.as_view(), name="manage_member_detail"),
    path("manage/members/<int:pk>/edit/", views.MemberEditView.as_view(), name="manage_member_edit"),
    path("manage/members/<int:pk>/deactivate/", views.MemberDeactivateView.as_view(), name="manage_member_deactivate"),
    path("manage/members/<int:pk>/reactivate/", views.MemberReactivateView.as_view(), name="manage_member_reactivate"),
    path("manage/members/<int:pk>/schedule/", views.MemberScheduleVersionCreateView.as_view(), name="manage_schedule_version_create"),

    # Calendar management
    path("manage/calendar/", views.HolidayCalendarView.as_view(), name="manage_calendar"),
    path("manage/calendar/holidays/create/", views.HolidayCreateView.as_view(), name="manage_holiday_create"),
    path("manage/calendar/holidays/<int:pk>/edit/", views.HolidayEditView.as_view(), name="manage_holiday_edit"),
    path("manage/calendar/holidays/<int:pk>/delete/", views.HolidayDeleteView.as_view(), name="manage_holiday_delete"),
    path("manage/calendar/policies/create/", views.CalendarPolicyCreateView.as_view(), name="manage_policy_create"),
]
