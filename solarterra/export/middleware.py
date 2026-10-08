class ExportMiddleware:

    def process(self, request):
        #returns None to continue down the middleware stack, HttpResponse to stop and send it to the user (django-style)
        #base class, every middleware must override this
        raise NotImplementedError

# ===CHECKS AND GATES===

# Middleware execution flow & request attribute lifecycle:
# all our request data lives in request.export_context (dict, set by dispatcher: job = ExportJob)
# [SizeCheckMiddleware]    → reads: job; adds: size
# [FormatChoiceMiddleware] → reads: size; adds: type
# [export_handler]         → reads all; returns HttpResponse

class SizeCheckMiddleware(ExportMiddleware):
    '''Rejects too big exports with 413 before any heavy lifting. Reads export_context["job"] (set by dispatcher), adds export_context["size"] (approx bytes).'''

    def process(self, request):
        from django.http import HttpResponse
        from export.config import get_max_export_size

        size = self.approximate_export_size(request)
        request.export_context["size"] = size
        max_size = get_max_export_size()
        if size > max_size:
            mb = lambda b: f"{b / 1024 ** 2:,.1f}"
            print(f"[EXPORT] SizeCheck rejected: ~{size} bytes > {max_size}")
            return HttpResponse(
                f"Превышен допустимый лимит экспорта: ~{mb(size)} МБ (лимит {mb(max_size)} МБ).\n"
                f"Сократите интервал времени, выберите меньше переменных или включите агрегацию.\n\n"
                f"Requested export is too large: ~{mb(size)} MB, limit is {mb(max_size)} MB.\n"
                f"Try a shorter time range, fewer variables, or aggregation.",
                status=413,
                content_type="text/plain; charset=utf-8",
            )
        return None

    def approximate_export_size(self, request):
        '''Raw CDF: real file sizes. Others: records x columns x BYTES_PER_VALUE per group, aggregation caps records at bin count.'''
        import os
        from export.config import BYTES_PER_VALUE
        from export.data_processing import Bin
        from export.raw_cdf.handlers import find_cdf_files
        from solarterra.utils import ts_float_resolver as tf

        job = request.export_context["job"]

        if job.export_format == "raw_cdf":
            return sum(os.path.getsize(f.full_path) for f in find_cdf_files(job.variables, job.ts_start, job.ts_end)
                       if os.path.exists(f.full_path))

        bytes_per_value = BYTES_PER_VALUE.get(job.export_format, 16)
        total = 0
        for item in job.var_groups():
            var_group = job.group_vars(item)
            depend_field = item.get_depend_field()
            if depend_field is None:
                continue
            records = item.dataset.dynamic.resolve_class().objects.filter(**{
                f"{depend_field.field_name}__gte": tf(job.ts_start),
                f"{depend_field.field_name}__lt": tf(job.ts_end),
            }).count()
            if job.aggregate:
                records = min(records, Bin.PPP)
            columns = 1 #epoch
            for var in var_group:
                for df in var.dynamic.all():
                    columns += df.array_size if df.is_array_field else 1
            total += records * columns * bytes_per_value
        return total

#TODO: will be implemented during auth module work

# class RateLimitMiddleware(ExportMiddleware):
#     '''Anti-DDOS measure: limits the number of export requests a single user can make per day.'''
#     def process(self, request):
#         from solar_project.solarterra.export.config import RATE_LIMIT_PER_USER_PER_DAY
#         user = self.get_user_from_request(request)
#         if self.get_user_request_count(user) >= RATE_LIMIT_PER_USER_PER_DAY:
#             return HttpResponse(status=429)  #429 = too many requests
#         return None

# class AuthCheckMiddleware(ExportMiddleware):
    #'''Checks if the user is authenticated, and what is allowed'''
#     def process(self, request):
#         pass

# class FormatChoiceMiddleware(ExportMiddleware):
#     def process(self, request):
#         if len(request.files) == 1:
#             request.export_context["type"] = "single"
#         elif len(request.files) <= 50:
#             request.export_context["type"] = "zip"
#         else:
#             request.export_context["type"] = "links"
#         return None

# ===HANDLER===
'''routes the flags-enriched response to the appropriate export handler based on the export type.'''

# def export_handler(request):
#     if request.export_context["type"] == "single":
#         return single_file_export(request)
#     elif request.export_context["type"] == "zip":
#         return multi_file_export(request)
#     else:
#         links = generate_download_links(request)
#         return render(request, "download_links.html", {"links": links})


#how to call it
'''
stack = MiddlewareStack(
    [
        AuthMiddleware(),
        RateLimitMiddleware(),
        SizeCheckMiddleware(),
        FormatChoiceMiddleware(),
    ],
    export_handler
)

response = stack.process(export_request)
'''