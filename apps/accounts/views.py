from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from .forms import EmailAuthenticationForm, OopswarePasswordChangeForm


class LoginView(auth_views.LoginView):
    template_name = "auth/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "auth/password_change.html"
    form_class = OopswarePasswordChangeForm
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been updated.")
        return super().form_valid(form)