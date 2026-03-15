from django.core.exceptions import ValidationError
from data_cdf.models import *
from load_cdf.models import Variable
from django import forms
import datetime as dt
from django.db.models import Q
from django.forms import Widget

class DateTimeWidget(forms.DateTimeInput):

    template_name = "widgets/datetime_widget.html"

    class Media:
        css = {
            "all" : ["datetime.css"]
        }
        js = [ "datetime.js" ]



class DateTimePicker(forms.DateTimeInput):

    template_name = "widgets/datetimepicker.html"

    class Media:
        css = {
            "all" : ["widgets/dateandtime.css"]
        }
        js = ["widgets/jquery-3.6.0.slim.min.js", "widgets/jquery.dateandtime.js" ]


class CustomCheckboxSelectMultiple(forms.CheckboxSelectMultiple):

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            option["attrs"]['id'] = f"actual-{value}"

        return option


class SourceForm(forms.Form):

    sources = forms.ModelMultipleChoiceField(
        label="Загруженные наборы данных",
        queryset=Variable.objects.plottable(),
        widget=CustomCheckboxSelectMultiple(),
        required=True,
    )

    ts_start = forms.DateTimeField(
        label="От",
        required=True,
        widget=DateTimeWidget(attrs={'id': "dtw_start"})
    )

    ts_end = forms.DateTimeField(
        label="До",
        required=True,
        widget=DateTimeWidget(attrs={'id': "dtw_end"})
    )

    def clean(self):
        cleaned_data = super().clean()
        ts_start = cleaned_data.get("ts_start")
        ts_end = cleaned_data.get("ts_end")

        if ts_start >= ts_end:
            raise ValidationError("Start time should be before end time.")

class PlotForm(forms.Form):
    validate = forms.BooleanField(
        label="Валидировать данные",
        required=False
    )


class ExportForm(forms.Form):
    EXPORT_FORMAT_CHOICES = (
        ("original_cdf", "Original CDF"),
        ("clean_cdf", "Clean CDF"),
        ("csv", "CSV"),
    )

    export_format = forms.ChoiceField(
        choices=EXPORT_FORMAT_CHOICES,
        required=True
    )