from django.shortcuts import render
from load_cdf.models import *
from data_cdf.models import *
from django.http import Http404, HttpResponse, StreamingHttpResponse, FileResponse
from django.apps import apps

from pages.forms import SourceForm, PlotForm, ExportForm
import datetime as dt
import csv, shutil, os, tempfile, zipfile


from pages.plotting import get_plots
from pages.export import plain_text_generator

DEFAULT_TIME_INTERVALS = {
    "test": {
        "ts_start": dt.datetime(year=2013, month=1, day=3, hour=0, minute=0),
        "ts_end": dt.datetime(year=2013, month=1, day=10, hour=0, minute=0),
    },
    "production": {
        "ts_start": dt.datetime(year=2013, month=1, day=1, hour=1),
        "ts_end": dt.datetime(year=2013, month=12, day=30, hour=1),
    },
}

#the time interval pre-set in the time selector widget; switch made for testing convenience
def _default_time_interval():
    return DEFAULT_TIME_INTERVALS["test"].copy()
    #return DEFAULT_TIME_INTERVALS["production"].copy()


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

# class Echo:
#     # csv.writer expects a file-like object with write(); return value is streamed chunk
#     def write(self, value):
#         return value

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
    aggregate = export_form.cleaned_data["aggregate"]

    print(
        f"[EXPORT] Request accepted. format={export_format}, sources={sources.count()}, "
        f"ts_start={ts_start}, ts_end={ts_end}, aggregate: {aggregate}"
    )

    if export_format != "plain_text": return HttpResponse("Only plain_text is implemented for now", status=501)

    #quiery containing a single var from a distinct group filtered by dataset tag and depend_0
    example_var_per_file = list(sources.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

    print(f"[EXPORT] Distinct file groups: {len(example_var_per_file)}")

    if len(example_var_per_file) == 1:

        item = example_var_per_file[0]
        dataset = item.dataset
        filename = f"{item.dataset.tag}_{item.depend_0}.txt"
        var_group = sources.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')

        print(f"[EXPORT] Single file streaming. Dataset: {item.dataset.tag}, depend_0: {item.depend_0}")

        print(f"[EXPORT] Streaming plain text file for dataset={dataset.tag}, depend_0={var_group[0].depend_0}, variables={len(var_group)}")
        response = StreamingHttpResponse(
            plain_text_generator(var_group, ts_start, ts_end, aggregate=aggregate),
            content_type="text/plain",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

    else: #safe, it's not zero, data is cleaned and form is verified

        print(f"[EXPORT] Multiple variable groups detected. Exporting each group as a separate file, expected filecount: {len(example_var_per_file)}")
        zip_timestamp = dt.datetime.now().strftime("%Y-%d-%m-%H-%M")
        zip_filename = f"exported_data_{zip_timestamp}.zip"
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = os.path.join(temp_dir, "exported_data")
            os.makedirs(export_dir, exist_ok=True)

            print(f"[EXPORT] Temp export dir: {export_dir}")

            for item in example_var_per_file:
                print(f"[EXPORT] Processing variable group: {item.dataset.tag} {item.depend_0}")
                var_group = sources.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
                filename = f"{item.dataset.tag}_{item.depend_0}.txt"
                filepath = os.path.join(export_dir, filename)

                with open(filepath, 'w', encoding='utf-8') as file_handle:
                    for line in plain_text_generator(var_group, ts_start, ts_end, aggregate=aggregate):
                        file_handle.write(line)

                print(f"[EXPORT] Wrote file: {filepath}")

            archive_base = os.path.join(temp_dir, "exported_data")
            resulting_zip_path = shutil.make_archive(archive_base, 'zip', export_dir)

            print(f"[EXPORT] Zip created: {resulting_zip_path}")

            with open(resulting_zip_path, 'rb') as zip_handle:
                zip_bytes = zip_handle.read()

            print(f"[EXPORT] Zip size in bytes: {len(zip_bytes)}")

            response = HttpResponse(zip_bytes, content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
            response["Content-Length"] = len(zip_bytes)

    return response


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