from django.core.management.base import BaseCommand
from django.db import transaction
from spacepy import pycdf
from load_cdf.models import *
from load_cdf.utils import *
from data_cdf.models import *
from solarterra.utils import ts_bigint_resolver as tbr
import timeit
import math
import numpy as np
from .evaluate_extras import command_logger, UploadRequired
from itertools import zip_longest


def save_single_file(cdf_file, fields, model_class, upload):

    cdf_obj = pycdf.CDF(cdf_file.full_path)
    arr_collection = []
    field_labels = []
    
    # numpy array work only
    for field in fields:
        var = field.variable_instance
        
        if field.is_array_field:
            # for ArrayField take the 2D matrix without cutting along the axes
            arr = cdf_obj[var.name][...]
            # for NRV
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
        else:
            arr = cdf_obj[var.name][...]
        
        if len(arr) == 0:
            make_log_entry(f"file '{cdf_file.full_path}' field '{field.field_name}' variable '{var.name}' contains no data", "WARNING", upload=upload)
            continue
            
        # there is no None numpy value for int types, and nan is a float
        # constructing python arrays will take up a lot more memory and time
        # so for now, i cast all numpy int array to object type to use None for invalid values
        
        if 'int' in str(arr.dtype):
            try:
                arr = arr.astype('object')
            except Exception as e:
                make_log_entry(f"Something went wrong during int to object array conversion: file '{cdf_file.full_path}' field '{field.field_name}': {e}", upload=upload)
                exit(1)

        # swap invalid datetime with None, everything else with np.nan
        if str(arr.dtype) == 'object':
            swap_value = None
        else:
            swap_value = np.nan
        
        # False will always propagate the other (significant) part of the OR operation
        condition = False
    
        #print("var: ", var.name, "fillval: ", var.fillval, "arr type", type(arr[0]), "fi", arr[0])
        # variable fillvals can differ from standard ones for the type: 017 command checks that
        # also fillval can change on the file level: #TODO add cdf file FILL_VAL and PAD_VALUE parsing here
        if var.fillval is not None:
            fill_value = DataType.proper_type(var.fillval, arr.flat[0])
            #print(f"FILL {fill_value}: {len(arr[arr==fill_value])} / {arr.shape}")
            #print("added fillval condition", var.fillval, type(arr[0]), fill_value, type(fill_value))
            if fill_value is None:
                make_log_entry("Could not parse fillval: file '{cdf_file.full_path}' variable '{var.name}' datatype '{data_type.cdf_file_label}', numpy type '{arr.dtype}'", "ERROR")
                exit(1)
            # choose values that are fillvals
            condition = condition | (arr == fill_value)
        
        # no parsing out values beyond valid interval: Maria`s request
        # that is happenning instead while plotting

        # check filter did not just stay False
        if isinstance(condition, np.ndarray):
            # filter all invalid values and swap them with nans
            arr[condition] = swap_value
        
        if 'float' in str(arr.dtype):
            nan_count = int(np.isnan(arr).sum())
            if nan_count > 0:
                make_log_entry(f"{nan_count} invalid values in '{field.field_name}' file '{cdf_file.full_path}'")
        
        # epoch parsing
        if field.data_type_instance.is_epoch():
            arr_collection.append(map(tbr, arr))
        # for ArrayField
        elif field.is_array_field:
            arr_collection.append([row.tolist() for row in arr])
        else:
            arr_collection.append(arr)

        # add attribute name for arrays with only non-zero entry counts
        field_labels.append(field.field_name)
    
    

    # zip by longest array instead of shrotest as in classic zip
    # only needed here as temporary solution for different depend fields (epochs) with different lengths
    zipped_collection = zip_longest(*arr_collection)
    instances = []
   
    
    for collection_row in zipped_collection:
        row_values = dict(zip(field_labels, collection_row))
        instances.append(model_class(cdf_file=cdf_file, **row_values))
    
    
    model_class.objects.bulk_create(instances)
    cdf_file.update(loaded=True, saved_rows=len(instances)) 
    print(len(instances)) 
    del arr_collection
    del zipped_collection
    del instances
    
    cdf_obj.close()

def delete_previous_file_data(cdf_file, model_class, upload):
    old_cdf_files = CDFFileStored.objects.filter(full_path=cdf_file.full_path).exclude(pk=cdf_file.pk)

    if not old_cdf_files.exists():
        return

    old_rows_qs = model_class.objects.filter(cdf_file__in=old_cdf_files)
    old_rows_count = old_rows_qs.count()
    old_rows_qs.delete()

    old_cdf_files.update(loaded=False, saved_rows=0)

    make_log_entry(
        f"Found previous version of file '{cdf_file.full_path}'. "
        f"Deleted {old_rows_count} old rows before reloading updated file.",
        "INFO",
        upload=upload
    )

class Command(UploadRequired, BaseCommand):

    help = "Command to load all data from the saved cdf files."

    requires_migrations_checks = True


    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)
    
    @command_logger
    def handle(self, *args, **options):
        
        upload_tag = options["upload_tag"][0]
        dataset_tag = options["dataset_tag"][0]
        try:
            upload = Upload.objects.get(u_tag=upload_tag, dataset__tag=dataset_tag)
        except:
            make_log_entry(f"Upload instance with upload_tag {upload_tag} and dataset_tag {dataset_tag} is not found.", "EXIT")
            exit(0)

        try:
            dynamic_model_instance = dmi = upload.dataset.dynamic
        except Exception as e:
            make_log_entry(f"Retrieving dynamic model instance: {e}", "ERROR", upload=upload)
            upload.terminate()

        try:
            model_class = dmi.resolve_class()
        except Exception as e:
            make_log_entry(f"Retrieving data model class: {e}", "ERROR", upload=upload)
            upload.terminate()
        
        if model_class is None:
            make_log_entry(f"Model class '{dmi.model_name}' is not found.", "ERROR", upload=upload)
            exit(1)
        else:
            make_log_entry(f"Resolved data model class '{dmi.model_name}'", "SUCCESS", upload=upload)

        
        cdf_files = upload.cdf_files.all()
        if cdf_files.count() == 0:
            make_log_entry("No new files found to upload. All files from this archive already exist in the dataset.", "INFO", upload=upload)
            return
        else:
            make_log_entry(f"{cdf_files.count()} files are to be uploaded to the db.", upload=upload)

        fields = dmi.fields.order_by('variable_instance__depend_0', 'id')

        file_count = cdf_files.count()
        percent = 0
        deltas = []


        for index, cdf_file in enumerate(cdf_files):
            if cdf_file.loaded:
                make_log_entry(f"File '{cdf_file.full_path}' is supposed to be loaded with {cdf_file.saved_rows}, skipping", upload=upload)
                continue
            t1 = timeit.default_timer()
            
            with transaction.atomic():
                delete_previous_file_data(cdf_file, model_class, upload)
                save_single_file(cdf_file, fields, model_class, upload) 
            
            t2 = timeit.default_timer() 
            deltas.append(t2 - t1)

            current_percent = math.floor(index / file_count * 100)
            
            if current_percent > percent:
                make_log_entry(f"{current_percent}% done, {index + 1} files uploaded, total time {round(sum(deltas), 5)}, avg time per file {round(sum(deltas) / len(deltas), 5)}", upload=upload)
                print(f"{current_percent}% done, {index + 1} files uploaded, total time {round(sum(deltas), 5)}, avg time per file {round(sum(deltas) / len(deltas), 5)}")
                percent = current_percent
