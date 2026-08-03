from django import forms

from .models import AccessoryType, Equipment

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


class StockAdjustForm(forms.Form):
    ACTIONS = (("add", "Add to stock"), ("remove", "Remove from stock"))

    action = forms.ChoiceField(
        choices=ACTIONS, widget=forms.Select(attrs={"class": INPUT})
    )
    quantity = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": INPUT})
    )
    reason = forms.CharField(widget=forms.TextInput(attrs={"class": INPUT}))
