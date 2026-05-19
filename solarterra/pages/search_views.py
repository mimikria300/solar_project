from django.shortcuts import render
from load_cdf.models import *
from data_cdf.models import *
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.apps import apps

from pages.forms import SourceForm, PlotForm, ExportForm

import datetime as dt
import tempfile, os, shutil

from pages.plotting import get_plots
from pages.export import plain_text_generator
from pages.export_instances import DataHandler, PlainTextMeta, Bin

#helper functions for search_view
def _default_source_interval():
    return {
        "ts_start": dt.datetime(year=2013, month=1, day=1, hour=1),
        "ts_end": dt.datetime(year=2013, month=12, day=30, hour=1),
    }


def _render_sources(request, *, source_form, plot_form, export_form, fresh=False, status=200):
    context = {
        "datasets": Dataset.objects.have_data().order_by("tag"),
        "source_form": source_form,
        "plot_form": plot_form,
        "export_form": export_form,
        "fresh": fresh,
    }
    return render(request, "pages/sources.html", context=context, status=status)


def search(request):

    if request.method != "GET":
        return HttpResponse("Search page expects GET", status=405)

    return _render_sources(
        request,
        source_form=SourceForm(initial=_default_source_interval()),
        plot_form=PlotForm(),
        export_form=ExportForm(),
        fresh=True,
    )

def export(request):
    if request.method != "POST":
        return HttpResponse("Export endpoint expects POST", status=405)

    source_form = SourceForm(data=request.POST)
    plot_form = PlotForm()  # unbound; only for consistent page rendering on invalid export
    export_form = ExportForm(data=request.POST)

    if not (source_form.is_valid() and export_form.is_valid()):
        return _render_sources(
            request,
            source_form=source_form,
            plot_form=plot_form,
            export_form=export_form,
            fresh=False,
            status=400,
        )

    sources = source_form.cleaned_data["sources"]
    ts_start = source_form.cleaned_data["ts_start"]
    ts_end = source_form.cleaned_data["ts_end"]

    export_format = export_form.cleaned_data["export_format"]
    aggregate = export_form.cleaned_data["aggregate"]
    validate = export_form.cleaned_data["validate"]

    print(
        f"[EXPORT] Request accepted. format={export_format}, sources={sources.count()}, "
        f"ts_start={ts_start}, ts_end={ts_end}, aggregate: {aggregate}, validate: {validate}"
    )

    #quiery containing a single var from a distinct group filtered by dataset tag and depend_0
    example_var_per_file = list(sources.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

    print(f"[EXPORT] Distinct file groups: {len(example_var_per_file)}")

    #CHECKPOINT: export format switch

    if export_format != "plain_text": return HttpResponse("Only plain_text is implemented for now", status=501)


    #CHECKPOINT: multifile handling

    if len(example_var_per_file) == 1:

        item = example_var_per_file[0]
        dataset = item.dataset
        filename = f"{item.dataset.tag}_{item.depend_0}.txt"
        var_group = sources.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
    

        print(f"[EXPORT] Single file streaming. Dataset: {item.dataset.tag}, depend_0: {item.depend_0}")

        print(f"[EXPORT] Streaming plain text file for dataset={dataset.tag}, depend_0={var_group[0].depend_0}, variables={len(var_group)}")
        response = StreamingHttpResponse(
            plain_text_generator(var_group, ts_start, ts_end, aggregate=aggregate, validate=validate),
            content_type="text/plain",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

    else: #safe, it's not zero, data is cleaned and form is verified

        #CHECKPOINT multifile zipping by var_group
    
        print(f"[EXPORT] Multiple variable groups detected. Exporting each group as a separate file, expected filecount: {len(example_var_per_file)}")
        zip_timestamp = dt.datetime.now().strftime("%Y-%d-%m-%H-%M")
        zip_intervalstamp = ''
        zip_filename = f"exported_data_{zip_timestamp + zip_intervalstamp}.zip"
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
                    for line in plain_text_generator(var_group, ts_start, ts_end, aggregate=aggregate, validate=validate):
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
    

    #return HttpResponse('Export stub!', status=200)

def plot(request):
    if request.method != "POST":
        return HttpResponse('Plot endpoint expects POST', status=405)

    source_form = SourceForm(data=request.POST)
    plot_form = PlotForm(data=request.POST)
    export_form = ExportForm()

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
    validate = source_form.cleaned_data['validate']
    plots = get_plots(var_instances, t_start, t_stop, validate)
  
    context = {
        't_start' : t_start,
        't_stop' : t_stop,
        'plots' : plots,

    }
    return render(request, "pages/plot_page.html", context=context)
