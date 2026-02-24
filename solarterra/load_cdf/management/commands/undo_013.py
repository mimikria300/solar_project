from django.core.management.base import BaseCommand
from load_cdf.models import *
from .evaluate_extras import UploadRequired

class Command(UploadRequired, BaseCommand):

    help = "Undo counterpart for #3 step in evaluation stage of the dataset upload.\n\
            Command deletes instances of DatasetAttribute, Variable and VariableAttribute"

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    def handle(self, *args, **options):
       
        upload = super().handle(**options)
        dataset = upload.dataset

        if upload.dataset_attributes_created:
            make_log_entry(f"Dataset attributes for dataset '{upload.dataset.tag}' were created during this upload {upload.u_tag}.")
            dataset_attributes = dataset.attributes.all()
            dataset_attributes.delete()
            upload.update(dataset_attributes_created=False)
            upload.update(matchfile_global_applied=False)
            make_log_entry(f"Deleted dataset attributes for dataset '{upload.dataset.tag}'", "DELETED")
        else:
            make_log_entry(f"Dataset attributes for dataset '{upload.dataset.tag}' were NOT created during this upload {upload.u_tag}. Skipping deletion.", "INFO")
        
        if upload.variables_created:
            make_log_entry(f"Variables for dataset '{upload.dataset.tag}' were created during this upload {upload.u_tag}.")
            variables = dataset.variables.all()
            variables.delete()
            upload.update(variables_created=False)
            upload.update(matchfile_vars_applied=False)
            make_log_entry(f"Deleted variables for dataset '{upload.dataset.tag}'", "DELETED")
        else:
            make_log_entry(f"Variables for dataset '{upload.dataset.tag}' were NOT created during this upload {upload.u_tag}. Skipping deletion.", "INFO")
