from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.accounts.models import Role


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Anonymous -> redirect to login. Wrong role -> 403.

    Authorization is always evaluated on the server from request.user.
    """

    required_role: str | None = None

    def test_func(self):
        return self.request.user.role == self.required_role


class AdminRequiredMixin(RoleRequiredMixin):
    required_role = Role.ADMIN


class MemberRequiredMixin(RoleRequiredMixin):
    """The 'User' role: employees and interns."""

    required_role = Role.USER