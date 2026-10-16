import calendar
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts import services as account_services
from apps.accounts.models import Role, User
from apps.core.permissions import AdminRequiredMixin
from apps.core import timeutils
from . import selectors as sched_selectors, services as sched_services
from .forms import (
    CalendarPolicyForm,
    HolidayForm,
    MemberCreateForm,
    MemberEditForm,
    WorkScheduleVersionForm,
)
from .models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule


class MembersListView(AdminRequiredMixin, View):
    template_name = "manage/members/list.html"

    def get(self, request):
        today = timeutils.local_date()
        users_qs = User.objects.filter(role=Role.USER).order_by("full_name")
        q = request.GET.get("q", "").strip()
        if q:
            users_qs = users_qs.filter(full_name__icontains=q) | users_qs.filter(email__icontains=q)

        paginator = Paginator(users_qs, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        user_ids = [u.id for u in page_obj.object_list]
        schedules_by_user = sched_selectors.get_schedules_map(user_ids, today, today)
        for u in page_obj.object_list:
            u.current_schedule = sched_selectors.schedule_for_user_from_cache(u.id, today, schedules_by_user)

        form = MemberCreateForm()
        return render(
            request,
            self.template_name,
            {
                "page_obj": page_obj,
                "create_form": form,
                "search_query": q,
            },
        )

    def post(self, request):
        form = MemberCreateForm(request.POST)
        if form.is_valid():
            try:
                user, temp_pw = account_services.create_user_account(
                    email=form.cleaned_data["email"],
                    full_name=form.cleaned_data["full_name"],
                    role=Role.USER,
                    actor=request.user,
                )
                sched_data = {
                    "effective_from": form.cleaned_data["effective_from"],
                    "start_time": form.cleaned_data["start_time"],
                    "end_time": form.cleaned_data["end_time"],
                    "late_grace_minutes": form.cleaned_data["late_grace_minutes"],
                    "absence_cutoff_minutes": form.cleaned_data["absence_cutoff_minutes"],
                    "working_weekdays": form.cleaned_data["working_weekdays"],
                }
                sched_services.create_schedule_version(user, sched_data, actor=request.user)
                messages.success(
                    request,
                    f"Member '{user.full_name}' created successfully. Temporary password: {temp_pw} (Copy this now; it will never be displayed again).",
                )
                return redirect("manage_members")
            except Exception as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Please correct the errors in the member creation form.")

        # Re-render with form errors
        today = timeutils.local_date()
        users_qs = User.objects.filter(role=Role.USER).order_by("full_name")
        paginator = Paginator(users_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {"page_obj": page_obj, "create_form": form, "search_query": ""},
        )


class MemberDetailView(AdminRequiredMixin, View):
    template_name = "manage/members/detail.html"

    def get(self, request, pk):
        member = get_object_or_404(User, pk=pk, role=Role.USER)
        schedules = member.schedules.all().order_by("-effective_from")
        open_sched = schedules.filter(effective_to__isnull=True).first()
        initial_from = (open_sched.effective_from + timedelta(days=1)) if open_sched else date.today()
        form = WorkScheduleVersionForm(initial={"effective_from": initial_from})
        edit_form = MemberEditForm(initial={"full_name": member.full_name})
        return render(
            request,
            self.template_name,
            {
                "member": member,
                "schedules": schedules,
                "schedule_form": form,
                "edit_form": edit_form,
            },
        )


class MemberEditView(AdminRequiredMixin, View):
    def post(self, request, pk):
        member = get_object_or_404(User, pk=pk, role=Role.USER)
        form = MemberEditForm(request.POST)
        if form.is_valid():
            member.full_name = form.cleaned_data["full_name"]
            member.full_clean()
            member.save(update_fields=["full_name"])
            messages.success(request, f"Updated profile for {member.full_name}.")
        else:
            messages.error(request, "Invalid name supplied.")
        return redirect("manage_member_detail", pk=pk)


class MemberDeactivateView(AdminRequiredMixin, View):
    def post(self, request, pk):
        member = get_object_or_404(User, pk=pk, role=Role.USER)
        try:
            account_services.deactivate_user(member, actor=request.user)
            messages.success(request, f"Member '{member.full_name}' has been deactivated.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect("manage_member_detail", pk=pk)


class MemberReactivateView(AdminRequiredMixin, View):
    def post(self, request, pk):
        member = get_object_or_404(User, pk=pk, role=Role.USER)
        try:
            account_services.reactivate_user(member, actor=request.user)
            messages.success(request, f"Member '{member.full_name}' has been reactivated.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect("manage_member_detail", pk=pk)


class MemberScheduleVersionCreateView(AdminRequiredMixin, View):
    def post(self, request, pk):
        member = get_object_or_404(User, pk=pk, role=Role.USER)
        form = WorkScheduleVersionForm(request.POST)
        if form.is_valid():
            try:
                sched_services.create_schedule_version(
                    member,
                    form.cleaned_data,
                    actor=request.user,
                )
                messages.success(request, "New work schedule version created.")
            except Exception as e:
                messages.error(request, str(e))
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field}: {err}")
        return redirect("manage_member_detail", pk=pk)


class HolidayCalendarView(AdminRequiredMixin, View):
    template_name = "manage/calendar/index.html"

    def get(self, request):
        today = timeutils.local_date()
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))

        # Clamp month and year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1

        cal = calendar.Calendar(firstweekday=0)  # Monday first
        month_days = cal.monthdatescalendar(year, month)

        # Preload for month
        first_day = month_days[0][0]
        last_day = month_days[-1][-1]
        holidays_map = sched_selectors.get_holidays_map(first_day, last_day)
        policies_list = sched_selectors.get_calendar_policies_list()

        weeks = []
        for week in month_days:
            week_data = []
            for d in week:
                cal_type, is_override = sched_selectors.calendar_day_type_from_cache(
                    d, holidays_map, policies_list
                )
                holiday = holidays_map.get(d)
                week_data.append({
                    "date": d,
                    "in_month": d.month == month,
                    "is_today": d == today,
                    "day_type": cal_type,
                    "is_override": is_override,
                    "is_second_sat": sched_selectors.is_second_saturday(d),
                    "holiday": holiday,
                })
            weeks.append(week_data)

        prev_month = (month - 1) if month > 1 else 12
        prev_year = year if month > 1 else (year - 1)
        next_month = (month + 1) if month < 12 else 1
        next_year = year if month < 12 else (year + 1)

        holidays_qs = Holiday.objects.filter(date__year=year).order_by("date")
        policies_qs = CalendarPolicy.objects.order_by("-effective_from")

        return render(
            request,
            self.template_name,
            {
                "year": year,
                "month": month,
                "month_name": calendar.month_name[month],
                "weeks": weeks,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "holidays": holidays_qs,
                "policies": policies_qs,
                "holiday_form": HolidayForm(),
                "policy_form": CalendarPolicyForm(initial={"effective_from": today}),
            },
        )


class HolidayCreateView(AdminRequiredMixin, View):
    def post(self, request):
        form = HolidayForm(request.POST)
        if form.is_valid():
            try:
                sched_services.create_holiday(
                    holiday_date=form.cleaned_data["date"],
                    name=form.cleaned_data["name"],
                    kind=form.cleaned_data["kind"],
                    actor=request.user,
                )
                messages.success(request, f"Added holiday/override '{form.cleaned_data['name']}'.")
            except Exception as e:
                messages.error(request, str(e))
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field}: {err}")
        return redirect("manage_calendar")


class HolidayEditView(AdminRequiredMixin, View):
    def post(self, request, pk):
        holiday = get_object_or_404(Holiday, pk=pk)
        name = request.POST.get("name", "").strip()
        kind = request.POST.get("kind", "").strip()
        if name and kind in HolidayKind.values:
            sched_services.update_holiday(holiday, name=name, kind=kind, actor=request.user)
            messages.success(request, f"Updated holiday '{name}'.")
        else:
            messages.error(request, "Invalid name or kind for holiday.")
        return redirect("manage_calendar")


class HolidayDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        holiday = get_object_or_404(Holiday, pk=pk)
        name = holiday.name
        sched_services.delete_holiday(holiday, actor=request.user)
        messages.success(request, f"Deleted holiday '{name}'.")
        return redirect("manage_calendar")


class CalendarPolicyCreateView(AdminRequiredMixin, View):
    def post(self, request):
        form = CalendarPolicyForm(request.POST)
        if form.is_valid():
            try:
                sched_services.create_calendar_policy(
                    effective_from=form.cleaned_data["effective_from"],
                    sunday_off=form.cleaned_data["sunday_off"],
                    second_saturday_off=form.cleaned_data["second_saturday_off"],
                    actor=request.user,
                )
                messages.success(request, "New calendar policy version created.")
            except Exception as e:
                messages.error(request, str(e))
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field}: {err}")
        return redirect("manage_calendar")
