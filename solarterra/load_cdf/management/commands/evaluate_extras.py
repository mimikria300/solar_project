from django.core.management.base import BaseCommand
from load_cdf.models import Upload, make_log_entry

# decorator to log command calls
def command_logger(func):
    
    def wrapper(*args, **kwargs):
        # trying to attach these logs to upload instance as well
        upload = None
        if 'upload_tag' in kwargs and 'dataset_tag' in kwargs:
            try:
                upload = Upload.objects.get(u_tag=kwargs["upload_tag"][0], dataset__tag=kwargs["dataset_tag"][0])
            except:
                # if it is not possible to attach this log to upload, just do not do it
                pass

        print("UPLOAD", upload)
        make_log_entry(f"In {func.__module__}:", "START", upload)
        func(*args, **kwargs)
        make_log_entry(f"Completed {func.__module__}", "EXIT", upload)
    
    return wrapper
    
# mixin that resolves the upload every time
class UploadRequired:

    def handle(self, *args, **options):
        upload_tag = options["upload_tag"][0]
        dataset_tag = options["dataset_tag"][0]
        try:
            upload = Upload.objects.get(u_tag=upload_tag, dataset__tag=dataset_tag)
            return upload
        except:
            make_log_entry(f"Upload instance with upload_tag {upload_tag} and dataset_tag {dataset_tag} is not found.", "EXIT")
            exit(0)

