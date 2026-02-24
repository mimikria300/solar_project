from django.core.management.base import BaseCommand
import os
import json
from django.conf import settings
from load_cdf.models import make_log_entry
from .evaluate_extras import command_logger

class Command(BaseCommand):

    help = "#0 step in evaluation stage of the dataset upload.\n\
            Command checks that both input files exist and are valid."

    def add_arguments(self, parser):
        parser.add_argument("zip_filename", nargs=1, type=str, help="Specify .zip filename")
        parser.add_argument("match_filename", nargs=1, type=str, help="Specify .json matchifle name")

    @command_logger
    def handle(self, *args, **options):

        zip_filename = options["zip_filename"][0]
        zip_path = os.path.join(settings.UPLOAD_ZIP_DIR, zip_filename)
        match_filename = options["match_filename"][0]
        match_file_path = os.path.join(settings.MATCH_FILE_DIR, match_filename)
        

        # Check if the zip file and match file exist
        if not zip_filename.endswith('.zip') or not os.path.isfile(zip_path):
            make_log_entry(f"zip file {zip_path} does not exist", "ERROR")
            make_log_entry("Terminating")
            exit(1)

        make_log_entry(f"Found file '{zip_path}'")

        if not match_filename.endswith('.json') or not os.path.isfile(match_file_path):
            make_log_entry(f"match_file {match_file_path} does not exist", "ERROR")
            make_log_entry("Terminating")
            exit(1)
        
        make_log_entry(f"Found file '{match_file_path}'")

        # Read the match file
        try:
            with open(match_file_path, 'r') as f:
                match_data = json.load(f)

            make_log_entry(f"Match file {match_filename} opens successfully.")

        except json.JSONDecodeError:
            make_log_entry(f"Error decoding JSON from match file: JSONDecodeError. Check if the file is a valid JSON.", "ERROR")
            exit(1)

        except Exception as e:
            make_log_entry(f"Error processing match file: {str(e)}", "ERROR")
            exit(1)





