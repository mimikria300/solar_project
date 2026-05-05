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
        input_formats=["%Y-%m-%d %H:%M:%S"],
        error_messages={
            "required": "Укажите начальную дату.",
            "invalid": "Введите дату строго в формате yyyy-mm-dd hh:mm:ss."
        },
        widget=DateTimeWidget(attrs={'id': "dtw_start"})
    )

    ts_end = forms.DateTimeField(
        label="До",
        required=True,
        input_formats=["%Y-%m-%d %H:%M:%S"],
        error_messages={
            "required": "Укажите конечную дату.",
            "invalid": "Введите дату строго в формате yyyy-mm-dd hh:mm:ss."
        },
        widget=DateTimeWidget(attrs={'id': "dtw_end"})
    )
    
    validate = forms.BooleanField(
        label="Валидировать данные",
        required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        ts_start = cleaned_data.get("ts_start")
        ts_end = cleaned_data.get("ts_end")

        if ts_start is not None and ts_end is not None:
            if ts_start >= ts_end:
                raise ValidationError("Start time should be before end time.")
        return cleaned_data
        
class PlotForm(forms.Form):
    ''' A stub for placing plot parameters later '''
    pass


class ExportForm(forms.Form):
    EXPORT_FORMAT_CHOICES = (
        ("plain_text", "Plain Text"),
        ("original_cdf", "Original CDF"),
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