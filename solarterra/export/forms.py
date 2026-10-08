from django.core.exceptions import ValidationError
#from load_cdf.models import Dataset, Variable
from django import forms

class ExportForm(forms.Form):
    EXPORT_FORMAT_CHOICES = (
        ("plain_text", "Plain Text"),
        ("raw_cdf", "Original CDF"),
        ("clean_cdf", "Clean CDF"),
    )

    export_format = forms.ChoiceField(
        choices=EXPORT_FORMAT_CHOICES,
        required=True
    )
    aggregate = forms.BooleanField(required=False, label="Агрегировать данные")
    validate = forms.BooleanField(
        label="Валидировать данные",
        required=False
    )