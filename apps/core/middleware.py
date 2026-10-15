from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Users flagged must_change_password can only reach the password-change page and logout."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.must_change_password:
            allowed = {reverse("password_change"), reverse("logout")}
            if request.path not in allowed and not request.path.startswith(
                "/" + settings.STATIC_URL.lstrip("/")
            ):
                return redirect("password_change")
        return self.get_response(request)