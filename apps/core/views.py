from datetime import timedelta
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from apps.attendance.models import AttendanceCorrectionRequest, CorrectionStatus
from apps.attendance.services import resolve_day
from apps.core.permissions import AdminRequiredMixin, MemberRequiredMixin
from apps.core import timeutils
from apps.scheduling import selectors as sched_selectors


class HomeView(LoginRequiredMixin, View):
    """Send each role to its own dashboard."""

    def get(self, request):
        return redirect("manage_dashboard" if request.user.is_admin else "user_dashboard")


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = "manage/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["today"] = timeutils.local_date()
        return ctx


class UserDashboardView(MemberRequiredMixin, TemplateView):
    template_name = "user/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timeutils.local_now()
        today = timeutils.local_date(now)
        user = self.request.user

        schedule = sched_selectors.schedule_for(user, today)
        status = resolve_day(user, today, now=now)

        can_check_in = False
        can_check_out = False
        button_disabled_reason = None

        if not schedule:
            button_disabled_reason = "No schedule is configured for you. Contact your administrator."
        else:
            if status.effective_check_in is None:
                is_working = sched_selectors.is_scheduled_working_day(user, today)
                start_dt = timeutils.make_aware_local(today, schedule.start_time)
                end_dt = timeutils.make_aware_local(today, schedule.end_time)
                early_limit = start_dt - timedelta(minutes=settings.CHECKIN_EARLY_MINUTES)

                if is_working:
                    if now < early_limit:
                        button_disabled_reason = f"Check-in opens at {schedule.start_time.strftime('%H:%M')} (up to {settings.CHECKIN_EARLY_MINUTES}m early)."
                    elif now > end_dt:
                        button_disabled_reason = "Workday has ended. Submit an attendance correction request."
                    else:
                        can_check_in = True
                else:
                    can_check_in = True
            elif status.effective_check_out is None:
                can_check_out = True
            else:
                button_disabled_reason = "Checked out for today."

        pending_count = AttendanceCorrectionRequest.objects.filter(
            user=user, status=CorrectionStatus.PENDING
        ).count()

        ctx.update({
            "today": today,
            "now": now,
            "schedule": schedule,
            "status": status,
            "can_check_in": can_check_in,
            "can_check_out": can_check_out,
            "button_disabled_reason": button_disabled_reason,
            "pending_corrections_count": pending_count,
        })
        return ctx