import calendar
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.models import Role, User
from apps.core import timeutils
from apps.core.permissions import AdminRequiredMixin, MemberRequiredMixin
from apps.scheduling import selectors as sched_selectors
from . import services
from .forms import CorrectionReviewForm, CorrectionSubmissionForm
from .models import AttendanceCorrectionRequest, AttendanceRecord, CorrectionStatus


class UserCheckInView(MemberRequiredMixin, View):
    def post(self, request):
        res = services.check_in(request.user)
        if res.success:
            messages.success(request, res.message)
        else:
            messages.warning(request, res.message)
        return redirect("user_dashboard")


class UserCheckOutView(MemberRequiredMixin, View):
    def post(self, request):
        res = services.check_out(request.user)
        if res.success:
            messages.success(request, res.message)
        else:
            messages.warning(request, res.message)
        return redirect("user_dashboard")


class UserAttendanceView(MemberRequiredMixin, View):
    template_name = "user/attendance.html"

    def get(self, request):
        today = timeutils.local_date()
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))

        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1

        _, num_days = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)

        statuses_map = services.resolve_range([request.user], start=start_date, end=end_date)
        statuses = statuses_map.get(request.user, [])
        summary = services.summarize(statuses)

        prev_month = (month - 1) if month > 1 else 12
        prev_year = year if month > 1 else (year - 1)
        next_month = (month + 1) if month < 12 else 1
        next_year = year if month < 12 else (year + 1)

        return render(
            request,
            self.template_name,
            {
                "statuses": statuses,
                "summary": summary,
                "year": year,
                "month": month,
                "month_name": calendar.month_name[month],
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
            },
        )


class UserCorrectionsView(MemberRequiredMixin, View):
    template_name = "user/corrections.html"

    def get(self, request):
        requests_qs = AttendanceCorrectionRequest.objects.filter(user=request.user).order_by("-created_at")
        form = CorrectionSubmissionForm(initial={"work_date": timeutils.local_date()})
        return render(
            request,
            self.template_name,
            {"requests": requests_qs, "form": form},
        )

    def post(self, request):
        form = CorrectionSubmissionForm(request.POST)
        if form.is_valid():
            try:
                services.submit_correction(
                    user=request.user,
                    work_date=form.cleaned_data["work_date"],
                    correction_type=form.cleaned_data["type"],
                    requested_time=form.cleaned_data["requested_time"],
                    reason=form.cleaned_data["reason"],
                )
                messages.success(request, "Correction request submitted successfully.")
                return redirect("user_corrections")
            except ValidationError as e:
                for msg in (e.messages if hasattr(e, "messages") else [str(e)]):
                    messages.error(request, msg)
            except Exception as e:
                messages.error(request, str(e))
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field}: {err}")

        requests_qs = AttendanceCorrectionRequest.objects.filter(user=request.user).order_by("-created_at")
        return render(
            request,
            self.template_name,
            {"requests": requests_qs, "form": form},
        )


class AdminAttendanceView(AdminRequiredMixin, View):
    template_name = "manage/attendance/index.html"

    def get(self, request):
        today = timeutils.local_date()
        target_date_str = request.GET.get("date")
        if target_date_str:
            try:
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = today
        else:
            target_date = today

        user_filter_id = request.GET.get("user")
        users_qs = User.objects.filter(role=Role.USER, is_active=True).order_by("full_name")
        if user_filter_id:
            users = list(users_qs.filter(pk=user_filter_id))
        else:
            users = list(users_qs)

        # 1. Resolve range for selected date
        statuses_by_user = services.resolve_range(users, start=target_date, end=target_date)
        attendance_rows = []
        for u in users:
            s_list = statuses_by_user.get(u, [])
            status = s_list[0] if s_list else None
            attendance_rows.append({"user": u, "status": status})

        # 2. Exceptions section (prior 14 days up to today)
        lookback_start = today - timedelta(days=14)
        all_tracked = list(users_qs)
        lookback_statuses = services.resolve_range(all_tracked, start=lookback_start, end=today)

        exceptions = {
            "absent_today": [],
            "arrived_after_cutoff_today": [],
            "missing_checkout_past": [],
        }
        for u in all_tracked:
            for s in lookback_statuses.get(u, []):
                if s.date == today:
                    if s.presence == services.Presence.ABSENT:
                        exceptions["absent_today"].append({"user": u, "status": s})
                    elif s.arrived_after_cutoff:
                        exceptions["arrived_after_cutoff_today"].append({"user": u, "status": s})
                elif s.date < today:
                    if s.checkout_state == services.CheckoutState.MISSING:
                        exceptions["missing_checkout_past"].append({"user": u, "status": s})

        # 3. Corrections Queue
        pending_corrections = AttendanceCorrectionRequest.objects.filter(
            status=CorrectionStatus.PENDING
        ).select_related("user").order_by("created_at")

        return render(
            request,
            self.template_name,
            {
                "target_date": target_date,
                "target_date_str": target_date.strftime("%Y-%m-%d"),
                "users": users_qs,
                "selected_user_id": user_filter_id,
                "attendance_rows": attendance_rows,
                "exceptions": exceptions,
                "pending_corrections": pending_corrections,
                "review_form": CorrectionReviewForm(),
            },
        )


class AdminReviewCorrectionView(AdminRequiredMixin, View):
    def post(self, request, pk):
        req_obj = get_object_or_404(AttendanceCorrectionRequest, pk=pk)
        decision = request.POST.get("decision")
        comment = request.POST.get("comment", "")
        try:
            services.review_correction(
                request_obj=req_obj,
                reviewer=request.user,
                decision=decision,
                comment=comment,
            )
            messages.success(request, f"Correction request for {req_obj.user.full_name} has been {decision}.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect("manage_attendance")
