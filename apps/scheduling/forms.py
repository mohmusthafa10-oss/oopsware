from datetime import date, time

from django import forms

from apps.accounts.forms import StyledFormMixin
from .models import CalendarPolicy, Holiday, HolidayKind, WorkSchedule

WEEKDAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class MemberCreateForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(label="Email address")
    full_name = forms.CharField(label="Full name", max_length=150)
    effective_from = forms.DateField(
        label="Schedule effective from",
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=date.today,
    )
    start_time = forms.TimeField(
        label="Start time (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial=time(9, 30),
    )
    end_time = forms.TimeField(
        label="End time (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial=time(18, 30),
    )
    late_grace_minutes = forms.IntegerField(
        label="Late grace (minutes)",
        min_value=0,
        initial=0,
    )
    absence_cutoff_minutes = forms.IntegerField(
        label="Absence cutoff (minutes)",
        min_value=1,
        initial=60,
    )
    working_weekdays = forms.MultipleChoiceField(
        label="Working weekdays",
        choices=WEEKDAY_CHOICES,
        initial=[0, 1, 2, 3, 4, 5],
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_working_weekdays(self):
        vals = self.cleaned_data.get("working_weekdays")
        if not vals:
            raise forms.ValidationError("Select at least one working weekday.")
        return [int(x) for x in vals]


class MemberEditForm(StyledFormMixin, forms.Form):
    full_name = forms.CharField(label="Full name", max_length=150)


class WorkScheduleVersionForm(StyledFormMixin, forms.Form):
    effective_from = forms.DateField(
        label="Effective from date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    start_time = forms.TimeField(
        label="Start time (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial=time(9, 30),
    )
    end_time = forms.TimeField(
        label="End time (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial=time(18, 30),
    )
    late_grace_minutes = forms.IntegerField(
        label="Late grace (minutes)",
        min_value=0,
        initial=0,
    )
    absence_cutoff_minutes = forms.IntegerField(
        label="Absence cutoff (minutes)",
        min_value=1,
        initial=60,
    )
    working_weekdays = forms.MultipleChoiceField(
        label="Working weekdays",
        choices=WEEKDAY_CHOICES,
        initial=[0, 1, 2, 3, 4, 5],
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_working_weekdays(self):
        vals = self.cleaned_data.get("working_weekdays")
        if not vals:
            raise forms.ValidationError("Select at least one working weekday.")
        return [int(x) for x in vals]


class HolidayForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "kind"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class CalendarPolicyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CalendarPolicy
        fields = ["effective_from", "sunday_off", "second_saturday_off"]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
        }
