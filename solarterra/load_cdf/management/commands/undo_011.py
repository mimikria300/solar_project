from django.core.management.base import BaseCommand

import os
import datetime as dt
from django.conf import settings
from load_cdf.models import *
from load_cdf.utils import get_upload_tag, get_dataset_tag
from .evaluate_extras import UploadRequired


class Command(UploadRequired, BaseCommand):

    help = "Counterpart for the #1 step in evaluation stage of the dataset upload.\n\
            Removes upload instance and dataset instance if it was created during this upload."

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    def handle(self, *args, **options):
        
        upload = super().handle(**options)
        u_tag = upload.u_tag
        dataset_tag = upload.dataset.tag
        if upload.dataset_created:
            make_log_entry(f"Dataset instance '{dataset_tag}' was created during this upload {u_tag}.")
            dataset = Dataset.objects.get(id=upload.dataset.id)
            print(dataset)
            dataset.delete()
            make_log_entry(f"Deleted dataset {dataset_tag}", "DELETED")
        else:
            make_log_entry(f"Dataset '{dataset_tag}' was NOT created during this upload {u_tag}. Skipping deletion.", "INFO")
        
        upload.delete()
        make_log_entry(f"Update instance {u_tag} for dataset dataset {dataset_tag} is deleted.")

