from django.shortcuts import render
from load_cdf.models import *
from data_cdf.models import *
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.apps import apps

from pages.forms import SourceForm, PlotForm, ExportForm
import datetime as dt
import csv

from pages.plotting import get_plots
from pages.export import csv_generator

def _default_time_interval():
    return {
        "ts_start": dt.datetime(year=2013, month=1, day=1, hour=1),
        "ts_end": dt.datetime(year=2013, month=12, day=30, hour=1),
    }


def _render_sources(request, *, source_form, plot_form, export_form, fresh=False):
    context = {
        "datasets": Dataset.objects.have_data().order_by("tag"),
        "source_form": source_form,
        "plot_form": plot_form,
        "export_form": export_form,
        "fresh": fresh,
    }
    return render(request, "pages/sources.html", context=context)


def search(request):

    if request.method != "GET":
        return HttpResponse("Search page expects GET", status=405)

    return _render_sources(
        request,
        source_form=SourceForm(initial=_default_time_interval()),
        plot_form=PlotForm(),
        export_form=ExportForm(),
        fresh=True,
    )
    
#PIN export stuff
#BOOKMARK export stuff
class Echo:
    # csv.writer expects a file-like object with write(); return value is streamed chunk
    def write(self, value):
        return value

# def _csv_preview_stream(ts_start, ts_end, sources):

#     '''stub for testing the streaming export. It will yield a header and a few rows of data.'''
#     writer = csv.writer(Echo())
#     yield writer.writerow(["timestamp", "note"])
#     yield writer.writerow([ts_start.isoformat(), f"sources={len(sources)}"])
#     yield writer.writerow([ts_end.isoformat(), "streaming export preview"])


def export(request):
    if request.method != "POST":
        return HttpResponse("Export endpoint expects POST", status=405)

    source_form = SourceForm(data=request.POST) 
    plot_form = PlotForm(data=request.POST) 
    export_form = ExportForm(data=request.POST)

    if not (source_form.is_valid() and export_form.is_valid()):
        return _render_sources(
            request,
            source_form=source_form,
            plot_form=plot_form,
            export_form=export_form,
            fresh=False,
        )

    export_format = export_form.cleaned_data["export_format"]
    sources = source_form.cleaned_data["sources"]
    ts_start = source_form.cleaned_data["ts_start"]
    ts_end = source_form.cleaned_data["ts_end"]

    if export_format != "csv": return HttpResponse("Only csv is implemented for now", status=501)

    response = StreamingHttpResponse(
        csv_generator(sources, ts_start, ts_end),
        content_type="text/csv",
    )
    response["Content-Disposition"] = 'attachment; filename="export_preview.csv"'
    return response

#BOOKMARK plotting stuff

def plot(request):
    if request.method != "POST":
        return HttpResponse('Plot endpoint expects POST', status=405)

    source_form = SourceForm(data=request.POST)
    plot_form = PlotForm(data=request.POST)
    export_form = ExportForm(data=request.POST)

    if not (source_form.is_valid() and plot_form.is_valid()):
        return _render_sources(
            request,
            source_form=source_form,
            plot_form=plot_form,
            export_form=export_form,
            fresh=False,
            status=400,
        )

    var_instances = Variable.objects.filter(id__in=source_form.cleaned_data['sources'])
    t_start = source_form.cleaned_data['ts_start']
    t_stop = source_form.cleaned_data['ts_end']
    validate = plot_form.cleaned_data['validate']
    plots = get_plots(var_instances, t_start, t_stop, validate)
    #bin_instance = plots[0].bin_instance
    #print("BIN INSTANCE", bin_instance, bin_instance.bin_seconds)
    """ 
    left_form = SourceForm(initial={
        't_start' : bin_instance.t_previous(t_start), 
        't_end' : t_start, 
        'sources' : source_form.cleaned_data['sources']})
    right_form = SourceForm(initial={
        't_start' : t_stop, 
        't_end' : bin_instance.t_next(t_stop), 
        'sources' : source_form.cleaned_data['sources']})
    """
    context = {
        't_start' : t_start,
        't_stop' : t_stop,
        'plots' : plots,
        #'bin_instance' : bin_instance,
        #'left_form' : left_form,
        #'right_form' : right_form
        
    }
    return render(request, "pages/plot_page.html", context=context)

    #return HttpResponse('Plot stub is OK', status=200)