from django.core.management.base import BaseCommand
import os
from django.template.loader import render_to_string
from load_cdf.models import *
# from load_cdf.utils import *
from load_cdf.utils import safe_str
from .evaluate_extras import command_logger, UploadRequired

class Command(UploadRequired, BaseCommand):

    help = "Last step in evaluation process. Command creates data model template file."
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
        
        upload = super().handle(**options)

        try:
            dynamic_model = upload.dataset.dynamic
        except Exception as e:
            make_log_entry("Dynamic model instance: {e}", "ERROR", upload=upload)
            upload.terminate()


        if  os.path.exists(dynamic_model.model_file_path):
            make_log_entry(f"Data model file '{dynamic_model.model_file_path}' already exists.", "ERROR", upload=upload)
            exit(0)

        
        content = render_to_string('model.tpl', context={ 'dm_instance' : dynamic_model })

        with open(dynamic_model.model_file_path, "w+") as model_file:
            model_file.write(content)

        make_log_entry(f"Saved data model template file '{dynamic_model.model_file_path}'", "SUCCESS", upload=upload)



