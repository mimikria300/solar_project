
from django.http import HttpResponse
from export.plaintext.handlers import single_file_export, multi_file_export
from export.raw_cdf.handlers import raw_cdf_export
from export.clean_cdf.handlers import clean_cdf_export, multi_clean_cdf_export
from pages.forms import VariableSelectForm
from export.forms import ExportForm
from export.middleware import SizeCheckMiddleware
#from export.middleware import AuthMiddleware, RateLimitMiddleware, FormatChoiceMiddleware

MIDDLEWARE_LIST = [
        #AuthMiddleware(),
        #RateLimitMiddleware(),
        SizeCheckMiddleware(),
        #FormatChoiceMiddleware(),
    ]

def export_dispatcher(request):
    '''
    Main entry point for export requests.
    Determines the export mode based on the request parameters and calls the appropriate function.
    
    '''
    # Validate forms once, middleware + sections below read cleaned data from the request

    selected_missions = request.session.get("selected_missions") #barely needed but in case
    var_form = VariableSelectForm(data=request.POST, missions=selected_missions)
    export_form = ExportForm(data=request.POST)

    if not (var_form.is_valid() and export_form.is_valid()):
        # for safety, export_clicked view already does that
        return HttpResponse("Invalid export request", status=400)

    #one dict per form, not merged (both forms even have a "validate" field)
    request.var_data = var_form.cleaned_data
    request.export_data = export_form.cleaned_data

    # Run middleware stack to а) enrich the request and b) potentially short-circuit the processing

    for middleware in MIDDLEWARE_LIST:
        response = middleware.process(request)
        if response is not None:  # Short-circuit and return a middleware-specific responce
            return response

    # Extract parameters from request (e.g., dataset, variables, time range, aggregate, validate)

    export_format = request.export_data["export_format"]
    variables = request.var_data["variables"]
    ts_start = request.var_data["ts_start"]
    ts_end = request.var_data["ts_end"]

    aggregate = request.export_data["aggregate"]
    validate = request.export_data["validate"]

    #SECTION - raw_cdf
    if export_format == "raw_cdf": 
        return raw_cdf_export(variables, ts_start, ts_end)
    
    #SECTION - plain_text
    elif export_format == "plain_text": 

        # Determine if single file or multi-file export is needed
        #quiery containing a single var from a distinct group filtered by dataset tag and depend_0
        var_groups = list(variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))

        print(f"[EXPORT] Distinct file groups: {len(var_groups)}")

        dt_str = ts_start.strftime('%Y%m%d%H%M') + '_' + ts_end.strftime('%Y%m%d%H%M')
        mode_tag = f"{'agg' if aggregate else 'full'}_{'val' if validate else 'raw'}"

        # Call single_file_export or multi_file_export accordingly
        if len(var_groups) == 1:
            item = var_groups[0]
            var_group = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
            response = single_file_export(item.dataset, var_group, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)

        else: #safe, it's not zero, data is cleaned and form is verified
            response = multi_file_export(variables, var_groups, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)
        return response

    #SECTION - clean_cdf
    elif export_format == "clean_cdf": 

        #cdf per var group (dataset + depend_0), zip if many
        var_groups = list(variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'))
        dt_str = ts_start.strftime('%Y%m%d%H%M') + '_' + ts_end.strftime('%Y%m%d%H%M')
        mode_tag = f"{'agg' if aggregate else 'full'}_{'val' if validate else 'raw'}"

        if len(var_groups) == 1:
            item = var_groups[0]
            var_group = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
            return clean_cdf_export(item.dataset, var_group, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)
        return multi_clean_cdf_export(variables, var_groups, ts_start, ts_end, aggregate, validate, dt_str, mode_tag)
    
    #SECTION - unsupported format
    else: 
        return HttpResponse("Unsupported export format", status=501)


    
    