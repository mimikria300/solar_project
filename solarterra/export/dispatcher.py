
from django.http import HttpResponse
from export.plaintext.handlers import single_file_export, multi_file_export
from export.raw_cdf.handlers import raw_cdf_export
from export.clean_cdf.handlers import clean_cdf_export, multi_clean_cdf_export, make_vargroup_bundles
from pages.forms import VariableSelectForm
from export.forms import ExportForm
from export.middleware import SizeCheckMiddleware
from export.job import ExportJob
#from export.middleware import AuthMiddleware, RateLimitMiddleware, FormatChoiceMiddleware
import logging

logger = logging.getLogger('solarterra.export')

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

    var_data = var_form.cleaned_data
    export_data = export_form.cleaned_data
    job = ExportJob(
        export_format=export_data["export_format"],
        variables=var_data["variables"],
        ts_start=var_data["ts_start"],
        ts_end=var_data["ts_end"],
        aggregate=export_data["aggregate"],
        validate=export_data["validate"], #ExportForm's, not VariableSelectForm's
        split_by_day=export_data["split_by_day"],
        split_by_resolution=export_data["split_by_resolution"],
    )
    #everything we add to the request lives in ONE dict -> `del request.export_context` drops it all if something safety-related happens
    request.export_context = {"job": job}

    # Run middleware stack to а) enrich the request and b) potentially short-circuit the processing

    for middleware in MIDDLEWARE_LIST:
        response = middleware.process(request)
        if response is not None:  # Short-circuit and return a middleware-specific responce
            return response

    #SECTION - raw_cdf
    if job.export_format == "raw_cdf":
        return raw_cdf_export(job)
    
    #SECTION - plain_text
    elif job.export_format == "plain_text":

        # Determine if single file or multi-file export is needed
        #one var per distinct group (dataset tag + depend_0)
        var_groups = job.var_groups()

        logger.debug(f"distinct file groups: {len(var_groups)}")

        # Call single_file_export or multi_file_export accordingly
        if len(var_groups) == 1:
            item = var_groups[0]
            response = single_file_export(job, item.dataset, job.group_vars(item))

        else: #safe, it's not zero, data is cleaned and form is verified
            response = multi_file_export(job, var_groups)
        return response

    #SECTION - clean_cdf
    elif job.export_format == "clean_cdf":

        #cdf per dataset (all its var groups in one), or per var group if split by resolution; zip if many (split by day is always a zip)
        bundles = make_vargroup_bundles(job, job.var_groups())
        if len(bundles) == 1 and not job.split_by_day:
            return clean_cdf_export(job, *bundles[0])
        return multi_clean_cdf_export(job, bundles)
    
    #SECTION - unsupported format
    else: 
        return HttpResponse("Unsupported export format", status=501)


    
    