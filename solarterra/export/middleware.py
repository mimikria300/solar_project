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
        '''Raw CDF: real file sizes. Clean CDF (not aggregated): original files' bytes/second x requested span, once per dataset.
        Others (+ datasets w/o usable files): records x columns x BYTES_PER_VALUE per group, aggregation caps records at bin count.'''
        import os
        from export.config import BYTES_PER_VALUE
        from export.data_processing import Bin
        from export.raw_cdf.handlers import find_cdf_files
        from solarterra.utils import ts_float_resolver as tf

        job = request.export_context["job"]

        if job.export_format == "raw_cdf":
            return sum(os.path.getsize(f.full_path) for f in find_cdf_files(job.variables, job.ts_start, job.ts_end)
                       if os.path.exists(f.full_path))

        total = 0
        groups = job.var_groups()
        if job.export_format == "clean_cdf" and not job.aggregate:
            #clean CDF comes out about original size (Maria 09-28: "a day ~ an original file")
            #per file rate (size / its span) x its overlap with the request: yearly/odd-length files work, gaps cost nothing
            #per dataset, not per group: an original file already holds all its groups
            #overestimates a bit on purpose: originals hold all vars
            for dataset in {item.dataset for item in groups}:
                estimate = self._original_bytes_in_range(dataset, tf(job.ts_start), tf(job.ts_end))
                if estimate is not None:
                    total += estimate
                    groups = [item for item in groups if item.dataset != dataset]

        bytes_per_value = BYTES_PER_VALUE.get(job.export_format, 16)
        for item in groups:
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
        return int(total) #overlap scaling makes floats, bytes are whole

    @staticmethod
    def _original_bytes_in_range(dataset, tu_start, tu_end):
        '''Sum of the dataset's original CDF sizes, each scaled by its time overlap with [tu_start, tu_end].
        None if the dataset has no usable stored files at all (caller falls back to records x columns).'''
        import os
        from load_cdf.models import CDFFileStored

        #loaded only: a re-upload leaves the replaced file's old row behind (loaded=False), it would count twice
        files = CDFFileStored.objects.filter(upload__dataset=dataset, loaded=True, tu_start__isnull=False, tu_end__isnull=False)
        if not files.exists():
            return None

        total = 0
        #only files overlapping the request come out of the DB, so cost grows with the request, not the dataset
        overlapping = files.filter(tu_end__gt=tu_start, tu_start__lt=tu_end).values_list('tu_start', 'tu_end', 'file_size', 'full_path')
        for f_start, f_end, size, path in overlapping:
            if f_end <= f_start:
                continue
            if size is None: #registered before file_size existed and not backfilled -> disk
                if not os.path.exists(path):
                    continue
                size = os.path.getsize(path)
            overlap = min(f_end, tu_end) - max(f_start, tu_start)
            total += size * overlap / (f_end - f_start)
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