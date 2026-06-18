from django.core.management.base import BaseCommand
import os
from django.conf import settings
from load_cdf.models import *
from load_cdf.utils import safe_str
from .evaluate_extras import command_logger, UploadRequired


class Command(UploadRequired, BaseCommand):

    help = "#6 step in evaluation stage of the dataset upload.\n\
            Command creates dynamic model and dynamic variable instances.\n\
            Has undo counterpart undo_016 that deletes dynamic model and dynamic variable instances"
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
       
        upload = super().handle(**options)
        dataset = upload.dataset

        if hasattr(dataset, 'dynamic') and dataset.dynamic is not None:
            make_log_entry("Dynamic model instance for the dataset is already found, skipping dynamic instances creation.", "FOUND", upload=upload)
            return

        model_file_name = dataset.tag + ".py"

        dynamic_model_instance = dmi = DynamicModel(
            model_name=f"{dataset.tag}{settings.MODEL_POSTFIX}",
            dataset_instance=dataset,
            model_file_path=os.path.join(settings.MODEL_DIR_PATH, model_file_name)
        )

        dmi.save()
        upload.update(dynamic_model_created=True)
        make_log_entry(f"Saved Dynamic Model instance for dataset {dataset.tag}", "CREATED", upload=upload)

        # dims attribute is unset (null) on variables that contain a single entry (scalar), not an array, e.g. axi(e)s label(s), so filtering them out here
        variables = dataset.variables.filter(dims__isnull=False)
        make_log_entry(f"Data from {variables.count()}/{dataset.variables.count()} variables will be saved in the db.", "INFO", upload=upload)
        
        if variables.count() == 0:
            make_log_entry("0 non-scalar variables found in the dataset.", "ERROR", upload=upload)
            exit(1)
    
        for variable in variables:
            var_name = safe_str(variable.name)
            print(f"var '{var_name}', dims {variable.dims}, dim_sizes {variable.dim_sizes}, labels {variable.lablaxis}")

            if variable.is_nrv():
                continue

            if variable.dims == 0:
                dmi.df_list.append(DynamicField(
                    field_name=var_name,
                    is_array_field=False,
                    variable_instance=variable,
                    dynamic_model=dmi
                ))
                make_log_entry(f"Added dynamic field '{dmi.df_list[-1]}' for variable '{variable.name}'", upload=upload)

            elif variable.dims == 1:
                if variable.dim_sizes is None:
                    make_log_entry(f"Variable '{variable.name}' with dims = {variable.dims} does not have dim_sizes set", "ERROR", upload=upload)
                    upload.terminate()
                
                dmi.df_list.append(DynamicField(
                    field_name=var_name,
                    is_array_field=True,
                    array_size=variable.dim_sizes,
                    variable_instance=variable,
                    dynamic_model=dmi
                ))
                
                make_log_entry(
                    f"Added ARRAY dynamic field '{var_name}' (size={variable.dim_sizes}) for variable '{variable.name}'", upload=upload)
            else:
                make_log_entry(f"Number of dimensions '{variable.dims}' in '{variable.name}' is not supported yet, skipping field creation", "WARNING", upload=upload)
                continue

        DynamicField.objects.bulk_create(dmi.df_list)
        make_log_entry(f"Saved {dmi.fields.count()} data fields for model {dmi.model_name}", "CREATED", upload=upload)
        del dmi.df_list
