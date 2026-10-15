from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class EmailAuthenticationForm(StyledFormMixin, AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Incorrect email or password.",
    }


class OopswarePasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def clean_new_password1(self):
        new = self.cleaned_data["new_password1"]
        if new and new == self.data.get("old_password"):
            raise forms.ValidationError("Choose a password different from your current one.")
        return new

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = False
        if commit:
            user.save()
        return user