from django import forms

from apps.accounts.forms import StyledFormMixin
from .models import CorrectionType


class CorrectionSubmissionForm(StyledFormMixin, forms.Form):
    work_date = forms.DateField(
        label="Work date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    type = forms.ChoiceField(
        label="Correction type",
        choices=CorrectionType.choices,
    )
    requested_time = forms.TimeField(
        label="Requested time (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    reason = forms.CharField(
        label="Reason for request",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Explain the circumstances requiring this correction..."}),
    )


class CorrectionReviewForm(StyledFormMixin, forms.Form):
    decision = forms.ChoiceField(
        choices=[("approved", "Approve"), ("rejected", "Reject")],
        widget=forms.HiddenInput,
    )
    comment = forms.CharField(
        label="Admin comment",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Reason (required if rejecting)..."}),
    )

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("decision")
        comment = cleaned_data.get("comment", "").strip()
        if decision == "rejected" and not comment:
            self.add_error("comment", "A comment is required when rejecting a correction request.")
        return cleaned_data
