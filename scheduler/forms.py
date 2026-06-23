from django import forms

from .models import Trip


class TripForm(forms.ModelForm):
    class Meta:
        model = Trip
        fields = ["title", "destination", "start_date", "end_date", "duration_days"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Alps weekend", "autocomplete": "off"}),
            "destination": forms.TextInput(attrs={"placeholder": "Optional", "autocomplete": "off"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "duration_days": forms.NumberInput(attrs={"min": 1, "max": 365, "value": 3}),
        }

