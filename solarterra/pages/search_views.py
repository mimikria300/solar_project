from django.shortcuts import render, redirect
from load_cdf.models import *
from data_cdf.models import *
from django.http import HttpResponse
from django.apps import apps
from pages.forms import MissionSelectForm, VariableSelectForm, PlotForm
from export.forms import ExportForm
from export.export import single_file_export, multi_file_export
import datetime as dt

from pages.plotting import get_plots
from export.export import single_file_export, multi_file_export

'''
NB: for convinience ts_start is always in timestamp format. 
The corresponding value in unixtime shall be named as tu_start.
'''


def select_missions(request):
    if request.method == "POST":
        form = MissionSelectForm(request.POST)
        if form.is_valid():
            request.session["selected_missions"] = form.cleaned_data["missions"]
            return redirect("select_variables")
    else:
        form = MissionSelectForm()

    return render(request, "pages/mission_select.html", context={"form": form})


def select_variables(request):
    '''Render the variable selection page. Only GET is accepted, POST on var_selection page calls plot/export views.'''

    selected_missions = request.session.get("selected_missions")

    if not selected_missions:
        return redirect("select_missions")

    datasets = (
            Dataset.objects.have_data()
            .filter(mission__in=selected_missions)
            .order_by("mission", "tag")
        )

    # ---FRESH PAGE---
    if request.method == "GET":

        var_form = VariableSelectForm(
            missions=selected_missions,
            initial={
                'ts_start': dt.datetime(year=2013, month=1, day=1, hour=0),
                'ts_end': dt.datetime(year=2013, month=12, day=30, hour=0),
            }
        )

        plot_form = PlotForm()
        export_form = ExportForm()

    # ---RENDER---
    context = {
        'datasets': datasets,
        'var_form': var_form,
        'plot_form': plot_form,
        'export_form': export_form,
        'selected_missions': selected_missions,
        "has_errors": any([bool(var_form.errors), bool(plot_form.errors), bool(export_form.errors)]),
    }

    return render(request, "pages/variable_select.html", context)


def shift_interval(t_start, t_stop, direction):
    shift_map = {
        "prev": (-1, 1),
        "prev_half": (-1, 2),
        "prev_quarter": (-1, 4),
        "next_quarter": (1, 4),
        "next_half": (1, 2),
        "next": (1, 1),
    }

    shift_config = shift_map.get(direction)
    if shift_config is None:
        return t_start, t_stop

    sign, divisor = shift_config
    interval = t_stop - t_start
    shift = interval / divisor

    if sign < 0:
        return t_start - shift, t_stop - shift

    return t_start + shift, t_stop + shift


def plot_clicked(request):
    '''
    Is called while the user is on the variable selection page and clicks "Plot". Expects POST with form data.
    Opens the plot page with the generated plots in the new tab. If form data is invalid, re-render variable selection page with errors.
    '''
    if request.method != "POST":
        return HttpResponse('Plot endpoint expects POST', status=405)
    
    selected_missions = request.session.get("selected_missions")
    datasets = (
        Dataset.objects.have_data()
        .filter(mission__in=selected_missions)
        .order_by("mission", "tag")
    )

    #reinstate forms with POST data
    var_form = VariableSelectForm(request.POST, missions=selected_missions)
    plot_form = PlotForm(request.POST) 
    export_form = ExportForm(request.POST)

    #go for plotting if forms are valid, otherwise re-render with errors
    if var_form.is_valid() and plot_form.is_valid():

        #var_form data
        var_instances = var_form.cleaned_data['variables']
        ts_start = var_form.cleaned_data['ts_start']
        ts_stop = var_form.cleaned_data['ts_end']
        validate = var_form.cleaned_data['validate']

        #place to get plot parameters from plot_form if needed
        #some_plot_param = plot_form.cleaned_data['some_plot_param']

        shift_direction = request.POST.get("shift")
        ts_start, ts_stop = shift_interval(ts_start, ts_stop, shift_direction)

        #get plots
        plots = get_plots(var_instances, ts_start, ts_stop, validate)

        for plot in plots:
            print(
                f"[invalid_values] dataset={plot.variable.dataset.tag}, "
                f"variable={plot.variable.name}, "
                f"invalid_values={plot.invalid_values}"
            )

        context = {
            't_start' : ts_start, #t_start is named like that bc is unrefactored yet in the template
            't_stop' : ts_stop,
            'validate': validate,
            'plots' : plots,
            'selected_variable_ids': list(var_instances.values_list("id", flat=True)),
        }
        return render(request, "pages/plot_page.html", context=context)

    #forms aren't ok, re-render search page with errors
    else:

        context = {
            'datasets': datasets,
            'var_form': var_form,
            'plot_form': plot_form,
            'export_form': export_form,
            'selected_missions': selected_missions,
            "has_errors": any([bool(var_form.errors), bool(plot_form.errors), bool(export_form.errors)]),
        }

        return render(request, "pages/variable_select.html", context)


    if var_form.is_valid() and export_form.is_valid():

        #export_format = export_form.cleaned_data["export_format"]
        variables = var_form.cleaned_data["variables"]
        ts_start = var_form.cleaned_data["ts_start"]
        ts_end = var_form.cleaned_data["ts_end"]

        return HttpResponse('Export stub!', status=200)

    #forms aren't ok, re-render search page with errors
    else:

        context = {
            'datasets': datasets,
            'var_form': var_form,
            'plot_form': plot_form,
            'export_form': export_form,
            'selected_missions': selected_missions,
            "has_errors": any([bool(var_form.errors), bool(plot_form.errors), bool(export_form.errors)]),
        }

        return render(request, "pages/variable_select.html", context)

def export_clicked(request):
    if request.method != "POST":
        return HttpResponse("Export endpoint expects POST", status=405)

    #reinstate forms with POST data
    selected_missions = request.session.get("selected_missions")
    var_form = VariableSelectForm(data=request.POST, missions=selected_missions)
    plot_form = PlotForm(data=request.POST)
    export_form = ExportForm(data=request.POST)

    if var_form.is_valid() and export_form.is_valid():

        export_format = export_form.cleaned_data["export_format"]
        variables = var_form.cleaned_data["variables"]
        ts_start = var_form.cleaned_data["ts_start"]
        ts_end = var_form.cleaned_data["ts_end"]

        aggregate = export_form.cleaned_data["aggregate"]
        validate = export_form.cleaned_data["validate"]

        print(
            f"[EXPORT] Request accepted. format={export_format}, variables={variables.count()}, "
            f"ts_start={ts_start}, ts_end={ts_end}, aggregate: {aggregate}, validate: {validate}"
        )

        # Handle raw_cdf export
        if export_format == "raw_cdf":
            from export.export import raw_cdf_export
            # responce = raw_cdf_export(variables, ts_start, ts_end)
            return raw_cdf_export(selected_missions, variables, ts_start, ts_end)

        if export_format != "plain_text": 
            return HttpResponse("Only plain text and raw CDF exports are implemented for now", status=501)

        #quiery containing a single var from a distinct group filtered by dataset tag and depend_0
        var_groups = list(variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

        print(f"[EXPORT] Distinct file groups: {len(var_groups)}")

        dt_str = ts_start.strftime('%Y%m%d%H%M') + '_' + ts_end.strftime('%Y%m%d%H%M')
        mode_tag = f"{'agg' if aggregate else 'full'}_{'val' if validate else 'raw'}"

        if len(var_groups) == 1:
            item = var_groups[0]
            var_group = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
            response = single_file_export(item.dataset, var_group, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)

        else: #safe, it's not zero, data is cleaned and form is verified
            response = multi_file_export(variables, var_groups, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)

        return response

    #forms aren't ok, re-render search page with errors
    else:

        context = {
            'var_form': var_form,
            'plot_form': plot_form,
            'export_form': export_form,
            'selected_missions': selected_missions,
            "has_errors": any([bool(var_form.errors), bool(plot_form.errors), bool(export_form.errors)]),
        }

        return render(request, "pages/variable_select.html", context)