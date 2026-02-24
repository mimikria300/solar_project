from django.core.management.base import BaseCommand
import os
import datetime as dt
from django.conf import settings
from load_cdf.models import *
from load_cdf.utils import get_upload_tag, get_dataset_tag
from .evaluate_extras import command_logger

class Command(BaseCommand):

    help = "#1 step in evaluation stage of the dataset upload.\n\
            Command creates upload instance and sets created or found dataset instance\n\
            Has counterpart undo_011 that removes upload instance and dataset instance if it was created during this upload"

    def add_arguments(self, parser):
        parser.add_argument("zip_filename", nargs=1, type=str)
        parser.add_argument("match_filename", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
        
        zip_filename = options["zip_filename"][0]
        zip_path = os.path.join(settings.UPLOAD_ZIP_DIR, zip_filename)
        match_filename = options["match_filename"][0]
        match_file_path = os.path.join(settings.MATCH_FILE_DIR, match_filename)

        dataset_tag = get_dataset_tag(zip_filename)
        upload_tag = get_upload_tag(zip_filename)

        # Create an Upload instance
        upload = Upload(
            created=dt.datetime.now(),
            u_tag=upload_tag,
            zip_path=zip_path,
            match_file_path=match_file_path
        )

        upload.save()
        # Log the upload creation
        make_log_entry(f"Created upload instance for {zip_filename} and {match_filename}.", "CREATED", upload=upload)

        dataset_dir_path = os.path.join(settings.DATA_ROOT, dataset_tag.replace('_', '/'))

        # create dataset instance if it doesnt exist and link it to upload
        dataset = Dataset.objects.get_or_none(tag=dataset_tag)
        if dataset is None:
            # Create a new dataset if it doesn't exist
            dataset = Dataset(
                    tag=dataset_tag,
                    directory=str(dataset_dir_path)
                    )
            dataset.save()
            make_log_entry(f"Dataset instance created for {dataset.tag}", "CREATED", upload=upload)
            upload.update(dataset_created = True)

        else:
            make_log_entry(f"Dataset instance already exists for {dataset_tag}.", "FOUND EXISTING", upload=upload)

        upload.dataset = dataset

        try:
            upload.save()
        except:
            make_log_entry(f"Upload instance for dataset '{dataset.tag}' with upload_tag '{upload.u_tag}' exists.", "ERROR", upload=upload)
            upload.terminate()


