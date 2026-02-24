from django.core.management.base import BaseCommand
from load_cdf.models import make_log_entry
import json
from .evaluate_extras import command_logger, UploadRequired

class Command(UploadRequired, BaseCommand):

    help = "#4 step in evaluation stage of the dataset upload.\n\
            Command saves global attributes from the matchfile to the dataset instance"
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
        
        upload = super().handle(**options)

        with open(upload.match_file_path, 'r') as f:
            match_data = json.load(f)
       
        dataset = upload.dataset
        global_attrs = match_data['GlobalAttributes']
        upload.update(matchfile_version = global_attrs['MATCHFILE_VERSION']['value'])
        global_attrs.pop('MATCHFILE_VERSION')

        # if dataset instance already exists, compare and contrast first
        # populate dataset fields from JSON
        for field in global_attrs.keys():
            print(f"FIELD {field} in global attr cycle")
            attribute = field.lower()
            value = global_attrs[field]['value']
            value = value if isinstance(value, str) else '\n'.join(value)

            if global_attrs[field]['gattribute_name'] is not None:
                try:
                    da_instance = dataset.attributes.get(title=global_attrs[field]['gattribute_name'])
                    da_instance.update(linked_standard_field = field)
                except:
                    make_log_entry(f"Global attribute '{field}' from match file not exist in the CDF", "WARNING", upload=upload)

            # if value is different, change it
            if getattr(dataset, attribute) != value:
                setattr(dataset, attribute, value)

                # notify if dataset hasn`t just been created
                if not upload.dataset_created:
                    make_log_entry(f"Replacing Dataset attribute {attribute} value '{getattr(dataset, attribute)}' with '{value}'", upload=upload)

        try:
            dataset.save()
            upload.update(matchfile_global_applied=True)
        except Exception as e:
            make_log_entry(f"When updating Dataset instance {dataset.tag} with global attributes from match file: {str(e)}", "ERROR", upload=upload)
        else:
            make_log_entry(f"Dataset instance {dataset.tag} updated with global attributes from match file", "SUCCESS", upload=upload)

