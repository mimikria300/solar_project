from django.core.management.base import BaseCommand
import os
from load_cdf.models import *
from .evaluate_extras import UploadRequired


class Command(UploadRequired, BaseCommand):

    help = "Counterpart for the #6 step in evaluation stage of the dataset upload.\n\
    Command deletes dynamic model and dynamic variable instances"
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    def handle(self, *args, **options):
       
        upload = super().handle(**options)
        if not hasattr(upload.dataset, 'dynamic'):
            make_log_entry(f"DynamicModel instance for dataset '{upload.dataset.tag}' not found. Skipping deletion", "NOT FOUND")
            return
        dynamic_model_instance = upload.dataset.dynamic
        # check if data model exists, and if it does, warn about coreect model disposal and migrations
        if os.path.exists(dynamic_model_instance.model_file_path):
            make_log_entry(f"Model file '{dynamic_model_instance.model_file_path}' exists. Delete it first.")
            data_model = dynamic_model_instance.resolve_class()
            print(data_model)
            if data_model is not None:
                # throws PropgrammingError if model is migrated
                try:
                    objs = data_model.objects.count()
                    make_log_entry(f"Data model '{dynamic_model_instance.model_name}' exists in the database and stores {objs} rows. After deleting its file, perform the migrations.")
                except Exception as e:
                    pass
            exit(1)

        if upload.dynamic_model_created:
            make_log_entry(f"DynamicModel and DynamicField instances for dataset '{upload.dataset.tag}' were created during this upload {upload.u_tag}.")
            dynamic_model_instance.delete()
            upload.update(dynamic_model_created=False)
            make_log_entry(f"Deleted DynamicModel and DynamicField instances for dataset '{upload.dataset.tag}'", "DELETED")
        else:
            make_log_entry(f"DynamicModel and DynamicField instances for dataset '{upload.dataset.tag}' were NOT created during this upload {upload.u_tag}. Skipping deletion.", "INFO")
