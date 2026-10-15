from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from apps.core.permissions import AdminRequiredMixin, MemberRequiredMixin
from apps.core.timeutils import local_date


class HomeView(LoginRequiredMixin, View):
    """Send each role to its own dashboard."""

    def get(self, request):
        return redirect("manage_dashboard" if request.user.is_admin else "user_dashboard")


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = "manage/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["today"] = local_date()
        return ctx


class UserDashboardView(MemberRequiredMixin, TemplateView):
    template_name = "user/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["today"] = local_date()
        return ctx