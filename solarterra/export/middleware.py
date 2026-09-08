class ExportMiddleware:

    def process(self, request):
        #returns True to continue with through middleware stack, False/Response to stop
        #this is a base class, so it short-circuits automatically
        raise NotImplementedError

# ===CHECKS AND GATES===

# Middleware execution flow & request attribute lifecycle:
# [FormatChoiceMiddleware] → reads: request.export_size; adds: request.export_type
# [export_handler]         → reads all; returns HttpResponse

#TODO: make the approx calculation logic

# class SizeCheckMiddleware(ExportMiddleware):

#     def process(self, request):
#         from solar_project.solarterra.export.config import EXPORT_MAX_SIZE_BYTES
#         approx_size = self.approximate_export_size(request)
#         if approx_size > EXPORT_MAX_SIZE_BYTES:
#             return False  #TODO: define what user sees when it doesn't pass check;return a Response indicating the size limit exceeded
#         return True

#     def approximate_export_size(self, request):
#         #TODO: implement logic to estimate export size based on request parameters
#         raise NotImplementedError

#TODO: will be imзlemented during auth module work

# class RateLimitMiddleware(ExportMiddleware):
#     '''Anti-DDOS measure: limits the number of export requests a single user can make per day.'''
#     def process(self, request):
#         from solar_project.solarterra.export.config import RATE_LIMIT_PER_USER_PER_DAY
#         user = self.get_user_from_request(request)
#         if self.get_user_request_count(user) >= RATE_LIMIT_PER_USER_PER_DAY:
#             return False
#         return True

# class AuthCheckMiddleware(ExportMiddleware):
    #'''Checks if the user is authenticated, and what is allowed'''
#     def process(self, request):
#         pass

# class FormatChoiceMiddleware(ExportMiddleware):
#     def process(self, request):
#         if len(request.files) == 1:
#             request.export_type = "single"
#         elif len(request.files) <= 50:
#             request.export_type = "zip"
#         else:
#             request.export_type = "links"
#         return True

# ===HANDLER===
'''routes the flags-enriched response to the appropriate export handler based on the export type.'''

def export_handler(request):
    if request.export_type == "single":
        return single_file_export(request)
    elif request.export_type == "zip":
        return multi_file_export(request)
    else:
        links = generate_download_links(request)
        return render(request, "download_links.html", {"links": links})


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