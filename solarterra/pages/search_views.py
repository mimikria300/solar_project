from django.shortcuts import render, redirect
from load_cdf.models import *
from data_cdf.models import *
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.apps import apps
from pages.forms import MissionSelectForm, VariableSelectForm, PlotForm, ExportForm
import datetime as dt
import tempfile, os, shutil

from pages.plotting import get_plots
from pages.export import plain_text_generator
from pages.export_instances import DataHandler, PlainTextMeta, Bin

'''
NB: for convinience ts_start is always in timestamp format. 
The corresponding value in unixtime shall be named as tu_start.
'''

def select_missions(request):
    if request.method == "POST":
        form = MissionSelectForm(request.POST)


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

def plot_clicked(request):
    '''
    Is called while the user is on the variable selection page and clicks "Plot". Expects POST with form data.
    Opens the plot page with the generated plots in the new tab. If form data is invalid, re-render variable selection page with errors.
    '''
    if request.method != "POST":
        return HttpResponse('Plot endpoint expects POST', status=405)

    #reinstate forms with POST data
    selected_missions = request.session.get("selected_missions")
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

        #get plots
        plots = get_plots(var_instances, ts_start, ts_stop, validate)

        context = {
            't_start' : ts_start, #t_start is named like that bc is unrefactored yet in the template
            't_stop' : ts_stop,
            'plots' : plots,          
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
            f"[EXPORT] Request accepted. format={export_format}, sources={sources.count()}, "
            f"ts_start={ts_start}, ts_end={ts_end}, aggregate: {aggregate}, validate: {validate}"
        )

        #quiery containing a single var from a distinct group filtered by dataset tag and depend_0
        example_var_per_file = list(sources.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

        print(f"[EXPORT] Distinct file groups: {len(example_var_per_file)}")

        #CHECKPOINT: export format switch

        if export_format != "plain_text": return HttpResponse("Only plain_text is implemented for now", status=501)

        dt_str = ts_start.strftime('%Y%m%d%H%M') + '_' + ts_end.strftime('%Y%m%d%H%M')
        mode_tag = f"{'agg' if aggregate else 'full'}_{'val' if validate else 'raw'}"
        #CHECKPOINT: multifile handling

        if len(example_var_per_file) == 1:

            item = example_var_per_file[0]
            dataset = item.dataset
            filename = f"{dt_str}_{item.dataset.tag}_{item.depend_0}_{mode_tag}.txt"
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
            zip_filename = f"exported_data_{zip_timestamp}.zip"
            with tempfile.TemporaryDirectory() as temp_dir:
                export_dir = os.path.join(temp_dir, "exported_data")
                os.makedirs(export_dir, exist_ok=True)

                print(f"[EXPORT] Temp export dir: {export_dir}")

                for item in example_var_per_file:
                    print(f"[EXPORT] Processing variable group: {item.dataset.tag} {item.depend_0}")
                    var_group = sources.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
                    filename = f"{dt_str}_{item.dataset.tag}_{item.depend_0}_{mode_tag}.txt"
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