from django import forms

from .models import Trip


class TripForm(forms.ModelForm):
    class Meta:
        model = Trip
        fields = [
            "title", "destination", "start_date", "end_date",
            "minimum_duration_days", "ideal_duration_days", "maximum_duration_days",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Alps weekend", "autocomplete": "off"}),
            "destination": forms.TextInput(attrs={"placeholder": "Optional", "autocomplete": "off"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "minimum_duration_days": forms.NumberInput(attrs={"min": 1, "max": 365, "value": 6}),
            "ideal_duration_days": forms.NumberInput(attrs={"min": 1, "max": 365, "value": 8}),
            "maximum_duration_days": forms.NumberInput(attrs={"min": 1, "max": 365, "value": 10}),
        }
