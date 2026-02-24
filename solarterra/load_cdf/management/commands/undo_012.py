from django.core.management.base import BaseCommand
import os
from django.conf import settings
from load_cdf.models import *
import shutil
from .evaluate_extras import command_logger, UploadRequired

# removing extra directories and their contents
def clean_path(data_root, dataset_dir_path):
    current_path = dataset_dir_path

    while current_path != data_root:
        if current_path != dataset_dir_path and any(os.scandir(current_path)):
            break

        make_log_entry(f"deleting directory {current_path}")
        shutil.rmtree(current_path, ignore_errors=True)
        current_path = current_path.rsplit('/', 1)[0]

class Command(UploadRequired, BaseCommand):

    help = "Counterpart for the #2 step in evaluation stage of the dataset upload.\n\
            Commmand cleans up the directory tree from this dataset`s files.\
            IF --no-rm flag IS SET NO FILESYSTEM DELETION IS PERFORMED.\
            This option is used for testing purposes: without deletion next normal upload of the same dataset will show collisions."

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)
        parser.add_argument("--no-rm", action="store_true", help="do not actually transfer the files (used for testing purposes)")


    def handle(self, *args, **options):

        upload = super().handle(**options)
        no_rm = options['no_rm']

        if upload.data_tree_created:
            make_log_entry(f"Filesystem directory '{upload.dataset.directory}' was created during this upload.")
            if no_rm:
                make_log_entry(f"--no-rm FLAG SET, NO DELETION ACTUALLY PERFORMED")
            else:
                clean_path(settings.DATA_ROOT, upload.dataset.directory)
            make_log_entry(f"Removed '{upload.dataset.directory}'")
            upload.update(data_tree_created=False) 
            cdf_files = CDFFileStored.objects.filter(upload=upload)
            cdf_files.delete()
            make_log_entry(f"Deleted all CDFFileStored instances for the dataset '{upload.dataset.tag}'", "DELETED")
        else:
            make_log_entry(f"Filesystem directory '{upload.dataset.directory}' was NOT created during this upload. Skipping deletion.")

