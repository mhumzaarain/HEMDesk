from django import forms

from .models import Accessory, AccessoryStatus, AccessoryType, Equipment

INPUT = (
    "w-full rounded border border-slate-300 px-3 py-2 "
    "focus:border-sky-500 focus:outline-none"
)


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = [
            "name",
            "manufacturer",
            "vendor",
            "model_number",
            "serial_number",
            "department",
            "is_critical_asset",
            "purchase_date",
            "installation_date",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "installation_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "is_critical_asset":
                field.widget.attrs.setdefault("class", INPUT)


class CondemnForm(forms.Form):
    remark = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}))
    condemned_location = forms.CharField(
        widget=forms.TextInput(attrs={"class": INPUT}),
        help_text="Current physical location of the condemned unit.",
    )


class AccessoryTypeForm(forms.ModelForm):
    class Meta:
        model = AccessoryType
        fields = ["name", "equipment_name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)
        self.fields["equipment_name"].widget.attrs.setdefault(
            "list", "equipment-name-options"
        )


class StockAdjustForm(forms.Form):
    ACTIONS = (("add", "Add to stock"), ("remove", "Remove from stock"))

    action = forms.ChoiceField(
        choices=ACTIONS, widget=forms.Select(attrs={"class": INPUT})
    )
    quantity = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": INPUT})
    )
    reason = forms.CharField(widget=forms.TextInput(attrs={"class": INPUT}))


class AccessoryAttachForm(forms.Form):
    accessory_type = forms.ModelChoiceField(
        queryset=AccessoryType.objects.all(),
        label="Accessory type",
        widget=forms.Select(attrs={"class": INPUT}),
    )
    serial_number = forms.CharField(
        required=False,
        help_text="Leave blank for non-serialized accessories.",
        widget=forms.TextInput(attrs={"class": INPUT}),
    )
    from_stock = forms.BooleanField(
        required=False,
        initial=True,
        label="Take from backup stock",
        help_text="Untick when cataloging an accessory that is already fitted.",
    )
    notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3, "class": INPUT})
    )


class AccessoryEditForm(forms.ModelForm):
    class Meta:
        model = Accessory
        fields = ["status", "serial_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Condemning is a separate, deliberate action with its own page.
        self.fields["status"].choices = [
            (AccessoryStatus.WORKING, "Working"),
            (AccessoryStatus.FAULTY, "Faulty"),
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)


class AccessoryCondemnForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}))


class AccessoryReplaceForm(forms.Form):
    remark = forms.CharField(
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
    serial_number = forms.CharField(
        required=False,
        help_text="Serial of the new unit; leave blank if not serialized.",
        widget=forms.TextInput(attrs={"class": INPUT}),
    )


class AccessoryRepairForm(forms.Form):
    remark = forms.CharField(
        label="What was done",
        widget=forms.Textarea(attrs={"rows": 3, "class": INPUT}),
    )
