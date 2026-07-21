from django.shortcuts import render, redirect
from pages.forms import MissionSelectForm, VariableSelectForm, PlotForm, ExportForm
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.apps import apps

from load_cdf.models import *

import datetime as dt
from pages.plotting import get_plots
#from pages.export import *


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
    interval = t_stop - t_start

    if direction == "prev":
        return t_start - interval, t_stop - interval

    if direction == "next":
        return t_start + interval, t_stop + interval

    return t_start, t_stop

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
        t_start = var_form.cleaned_data['ts_start']
        t_stop = var_form.cleaned_data['ts_end']
        validate = var_form.cleaned_data['validate']

        #place to get plot parameters from plot_form if needed
        #some_plot_param = plot_form.cleaned_data['some_plot_param']

        shift_direction = request.POST.get("shift")
        if shift_direction in {"prev", "next"}:
            t_start, t_stop = shift_interval(t_start, t_stop, shift_direction)

        #get plots
        plots = get_plots(var_instances, t_start, t_stop, validate)

        for plot in plots:
            print(
                f"[invalid_values] dataset={plot.variable.dataset.tag}, "
                f"variable={plot.variable.name}, "
                f"invalid_values={plot.invalid_values}"
            )

        context = {
            't_start' : t_start,
            't_stop' : t_stop,
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

def export_clicked(request):
    if request.method != "POST":
        return HttpResponse("Export endpoint expects POST", status=405)

    #reinstate forms with POST data
    selected_missions = request.session.get("selected_missions")
    var_form = VariableSelectForm(data=request.POST, missions=selected_missions)
    plot_form = PlotForm(data=request.POST)
    export_form = ExportForm(data=request.POST)

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

    