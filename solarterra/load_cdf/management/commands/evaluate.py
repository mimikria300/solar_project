from django.core.management.base import BaseCommand
from load_cdf.utils import get_dataset_tag, get_upload_tag
from django.conf import settings
from django.core import management
from load_cdf.models import make_log_entry

"""
This command accepts a single dataset represented with .zip file with data and .json file with metadata, \
unpacks the data into the subtree of the settings.DATA_ROOT and creates corresponding instances of Dataset, Variable and dependent models.

the call is:
    python manage.py evaluate <zip_filename> <matchfile_filename>

Both parameters are required.
"""


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument("zip_filename", nargs=1, type=str)
        parser.add_argument("match_filename", nargs=1, type=str)

    def handle(self, *args, **options):

        make_log_entry(f"\nStarting {str(self)}")
        make_log_entry(f"CURRENT UPLOAD_ZIP_DIR: {settings.UPLOAD_ZIP_DIR}")
        make_log_entry(f"CURRENT MATCH_FILE_DIR: {settings.MATCH_FILE_DIR}")
    
    
        zip_filename = options["zip_filename"][0]
        upload_tag = get_upload_tag(zip_filename)
        dataset_tag = get_dataset_tag(zip_filename)

        management.call_command("010_validate_input",  zip_filename,  options["match_filename"][0])
        management.call_command("011_create_managing_instances",  zip_filename,  options["match_filename"][0])
        management.call_command("012_filesystem_work",  upload_tag, dataset_tag)
        #management.call_command("012_filesystem_work",  upload_tag, dataset_tag, '--no-mv')
        management.call_command("013_cdffile_work",  upload_tag, dataset_tag)
        management.call_command("014_matchfile_global_attrs",  upload_tag, dataset_tag)
        management.call_command("015_matchfile_variables",  upload_tag, dataset_tag)
        management.call_command("016_create_dynamic_instances",  upload_tag, dataset_tag)
        management.call_command("017_datatype_work",  upload_tag, dataset_tag)
        management.call_command("018_create_data_model_template_file",  upload_tag, dataset_tag)
        
