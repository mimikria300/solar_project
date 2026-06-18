from django.core.management.base import BaseCommand
from load_cdf.models import *
from .evaluate_extras import command_logger, UploadRequired


class Command(UploadRequired, BaseCommand):

    help = "#7 step in evaluation stage of the dataset upload.\n\
            Command checks that all datatypes are supported: DataType instances for them exist, numpy types and fillvals for them are filled in and django fields are specified"
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
        
        upload = super().handle(**options)
        
        fieldset = upload.dataset.dynamic.fields.filter(data_type_instance__isnull=True)

        # open all dynamic_fields, check that datatype for ech one exist
        for field in fieldset:
            variable = field.variable_instance
            print(f"{field.field_name} {variable.datatype} {variable.fillval}")
            try:
                data_type_instance = DataType.objects.get(cdf_file_label=variable.datatype)
            except:
                make_log_entry(f"DataType instance for field '{field.field_name}' with cdf type '{variable.datatype}' is not supported", "ERROR", upload=upload)
                exit(1)
    
            field.update(data_type_instance = data_type_instance)

            if data_type_instance.django_field is None:
                make_log_entry(f"Field '{field.field_name}': '{variable.datatype}' default django field is unset. Will not be able to create model", "ERROR", upload=upload)
                exit(1)
            if data_type_instance.numpy_type is None:
                make_log_entry(f"Field '{field.field_name}': '{variable.datatype}' default numpy type is unset. Could create errors when plotting data", "WARNING", upload=upload)

            if data_type_instance.fillval != variable.fillval:
                make_log_entry(f"Field '{field.field_name}': '{variable.datatype}' default fillval is '{data_type_instance.fillval}', in this dataset '{variable.fillval}'", "WARNING", upload=upload)
