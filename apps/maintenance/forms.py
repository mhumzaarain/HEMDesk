from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Roles
from apps.equipment.models import Equipment

from .models import (
    CloseReason,
    Complaint,
    ComplaintStatus,
    FaultCategory,
    PPMInterval,
    PPMOutcome,
    RemarkKind,
)

INPUT = (
    "w-full rounded border border-slate-300 px-3 py-2 "
    "focus:border-sky-500 focus:outline-none"
)


class ComplaintForm(forms.Form):
    equipment = forms.ModelChoiceField(
        queryset=Equipment.objects.all(), widget=forms.HiddenInput
    )
    description = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": INPUT,
                "placeholder": "Describe what is wrong with the equipment…",
            }
        )
    )


class CloseComplaintForm(forms.Form):
    close_reason = forms.ChoiceField(
        choices=[
            (CloseReason.DUPLICATE, "Duplicate of another complaint"),
            (CloseReason.NO_FAULT, "No fault found"),
        ],
        widget=forms.RadioSelect,
    )
    duplicate_of = forms.ModelChoiceField(
        queryset=Complaint.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    close_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": INPUT}),
    )

    def __init__(self, *args, complaint=None, **kwargs):
        super().__init__(*args, **kwargs)
        if complaint is not None:
            self.fields["duplicate_of"].queryset = (
                Complaint.objects.filter(equipment=complaint.equipment)
                .exclude(pk=complaint.pk)
                .exclude(status=ComplaintStatus.CLOSED)
            )

    def clean(self):
        data = super().clean()
        if (
            data.get("close_reason") == CloseReason.DUPLICATE
            and not data.get("duplicate_of")
            and not data.get("close_note")
        ):
            raise forms.ValidationError(
                "Closing as duplicate needs the original complaint or a note."
            )
        return data


class CompleteWorkOrderForm(forms.Form):
    fault_category = forms.ModelChoiceField(
        queryset=FaultCategory.objects.all(),
        widget=forms.Select(attrs={"class": INPUT}),
    )
    participants = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.filter(
            role__in=[Roles.ENGINEER, Roles.ADMIN], is_active=True
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick every engineer who worked on this repair.",
    )
    remark = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": INPUT}),
    )


class RemarkForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "class": INPUT}))
    kind = forms.ChoiceField(
        choices=[
            (RemarkKind.NOTE, "Note"),
            (RemarkKind.DELAY, "Delay (explain why the repair is taking long)"),
        ],
        initial=RemarkKind.NOTE,
    )


class PPMScheduleForm(forms.Form):
    interval = forms.ChoiceField(
        choices=PPMInterval.choices,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    next_due = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT})
    )
    active = forms.BooleanField(required=False, initial=True)


class PPMCompleteForm(forms.Form):
    performed_at = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT})
    )
    outcome = forms.ChoiceField(
        choices=PPMOutcome.choices, widget=forms.RadioSelect
    )
    engineers = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.filter(
            role__in=[Roles.ENGINEER, Roles.ADMIN], is_active=True
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick every engineer who performed this PPM.",
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
    open_work_order = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        if data.get("open_work_order") and data.get("outcome") != PPMOutcome.FAILED:
            raise forms.ValidationError(
                "A work order can only be opened when the PPM failed."
            )
        return data
