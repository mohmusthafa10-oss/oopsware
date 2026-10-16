"""Idempotent attendance exceptions scanner.

Phase 7 will hang notifications off this command. No dashboard numbers or
business metrics depend on this command running; absences and exceptions are
dynamically derived from the clock via resolve_day and resolve_range.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User
from apps.attendance.services import CheckoutState, Presence, resolve_range
from apps.core import timeutils


class Command(BaseCommand):
    help = "Scan and print attendance exceptions (un-checked-in past cutoff today, missing checkouts from prior days)."

    def handle(self, *args, **options):
        now = timeutils.local_now()
        today = timeutils.local_date(now)
        lookback_start = today - timedelta(days=14)

        users = User.objects.filter(role=Role.USER, is_active=True).order_by("full_name")
        statuses_by_user = resolve_range(users, start=lookback_start, end=today, now=now)

        absent_today = []
        missing_checkouts = []

        for user, statuses in statuses_by_user.items():
            for s in statuses:
                if s.date == today:
                    if s.presence == Presence.ABSENT:
                        absent_today.append(f"{user.full_name} ({user.email})")
                elif s.date < today:
                    if s.checkout_state == CheckoutState.MISSING:
                        missing_checkouts.append(f"{user.full_name} ({user.email}) on {s.date}")

        self.stdout.write(f"=== Attendance Exceptions for {today} (evaluated at {now.strftime('%H:%M:%S')}) ===")
        self.stdout.write(f"Absent today (past cutoff): {len(absent_today)}")
        for item in absent_today:
            self.stdout.write(f"  - {item}")

        self.stdout.write(f"Missing checkouts (prior 14 days): {len(missing_checkouts)}")
        for item in missing_checkouts:
            self.stdout.write(f"  - {item}")
