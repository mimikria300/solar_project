
from django.http import HttpResponse
from export.plaintext.handlers import single_file_export, multi_file_export
from export.raw_cdf.handlers import raw_cdf_export
from pages.forms import VariableSelectForm
from export.forms import ExportForm
#from export.middleware import AuthMiddleware, RateLimitMiddleware, SizeCheckMiddleware, FormatChoiceMiddleware

MIDDLEWARE_LIST = [
        #AuthMiddleware(),
        #RateLimitMiddleware(),
        #SizeCheckMiddleware(),
        #FormatChoiceMiddleware(),
    ]

def export_dispatcher(request):
    '''
    Main entry point for export requests.
    Determines the export mode based on the request parameters and calls the appropriate function.
    
    '''
    # Run middleware stack to а) enrich the request and b) potentially short-circuit the processing

    #FIXME: check if request new fields persist?
    for middleware in MIDDLEWARE_LIST:
        result = middleware.process(request)
        if result is not True:  # Short-circuit and return a middleware-specific responce
            return result
    
    # Extract parameters from request (e.g., dataset, variables, time range, aggregate, validate)

    selected_missions = request.session.get("selected_missions") #barely needed but in case
    var_form = VariableSelectForm(data=request.POST, missions=selected_missions)
    export_form = ExportForm(data=request.POST)

    if not (var_form.is_valid() and export_form.is_valid()):
        # for safety, export_clicked view already does that
        return HttpResponse("Invalid export request", status=400)

    export_format = export_form.cleaned_data["export_format"]
    variables = var_form.cleaned_data["variables"]
    ts_start = var_form.cleaned_data["ts_start"]
    ts_end = var_form.cleaned_data["ts_end"]

    aggregate = export_form.cleaned_data["aggregate"]
    validate = export_form.cleaned_data["validate"]

    if export_format == "raw_cdf": #SECTION - raw_cdf
        return raw_cdf_export(variables, ts_start, ts_end)

    elif export_format == "plain_text": #SECTION - plain_text

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
    
    else: #SECTION - unsupported format
        return HttpResponse("Only plain text and raw CDF exports are implemented for now", status=501)


    
    