from django.core.exceptions import ValidationError
from load_cdf.models import Dataset, Variable
from django import forms


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

class MissionSelectForm(forms.Form):
    missions = forms.MultipleChoiceField(
        label="Миссии",
        required=True,
        widget=forms.CheckboxSelectMultiple,
        error_messages={
            "required": "Выберите хотя бы одну миссию."
        }
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        mission_values = (
            Dataset.objects.have_data()
            .exclude(mission__isnull=True)
            .exclude(mission="")
            .values_list("mission", flat=True)
            .distinct()
            .order_by("mission")
        )

        self.fields["missions"].choices = [(mission, mission) for mission in mission_values]

class VariableSelectForm(forms.Form):
    variables = forms.ModelMultipleChoiceField(
        label="Переменные",
        queryset=Variable.objects.none(),
        widget=CustomCheckboxSelectMultiple(),
        required=True,
        error_messages={
            "required": "Выберите хотя бы одну переменную."
        }
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

    def __init__(self, *args, missions=None, **kwargs):
        super().__init__(*args, **kwargs)

        queryset = Variable.objects.plottable()

        if missions:
            queryset = queryset.filter(dataset__mission__in=missions)
        else:
            queryset = queryset.none()

        self.fields["variables"].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()
        ts_start = cleaned_data.get("ts_start")
        ts_end = cleaned_data.get("ts_end")

        if ts_start is not None and ts_end is not None:
            if ts_start >= ts_end:
                raise ValidationError("Начальная дата должна быть раньше конечной.")
        return cleaned_data
        
class PlotForm(forms.Form):
    ''' A stub for placing plot parameters later '''
    pass
                
class ExportForm(forms.Form):
    ''' A stub for placing export parameters later '''
    pass