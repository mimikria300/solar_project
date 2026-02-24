from django.core.management.base import BaseCommand
from load_cdf.models import *
import json
from .evaluate_extras import command_logger, UploadRequired

def get_var_field(mf_str):
    if mf_str.startswith('MF_'):
        return mf_str[3:].lower()
    elif mf_str.startswith('MFLBL_'):
        return mf_str[6:].lower()
    else:
        raise Exception(f"Matchfile atribute '{mf_str}' does not have standard prefix.")

class Command(UploadRequired, BaseCommand):

    help = "#5 step in evaluation stage of the dataset upload.\n\
            Command updates variable and variable attribute instances with the data from the matchfile"
    
    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
        
        upload = super().handle(**options)

        with open(upload.match_file_path, 'r') as f:
            match_data = json.load(f)
      
        var_qs = upload.dataset.variables.all()

        for var_name, var_dict in match_data['Variables'].items(): 
            # find instance of this variable
            try:
                var_instance = var_qs.get(name=var_name)
            except Exception as e:
                make_log_entry(f"Variable '{var_name}' from match file does not exist in the CDF file.", "ERROR", upload=upload)
                upload.terminate()

            # setting attribute values for one variable
            for json_var_attr, var_attr_dict in var_dict.items():
                
                # parse out Variable field name
                try:
                    var_field = get_var_field(json_var_attr)
                except Exception as e:
                    make_log_entry(f"When parsing matchfile variable '{var_name}: {e}'", "ERROR", upload=upload)

                # set attribute value
                setattr(var_instance, var_field, var_attr_dict['value'])

                # find the var attr instance
                v_attr_name = var_attr_dict['vattribute_name']
                if v_attr_name is None:
                    continue
                try:
                    # case-insensitive query
                    var_attr_instance = var_instance.attributes.get(title__iexact=v_attr_name)
                    var_attr_instance.update(linked_standard_field=var_field)
                except Exception as e:
                    make_log_entry(f"VariableAttribute '{v_attr_name}' for Variable '{var_name}' from match file does not exist in the CDF file.", "WARNING", upload=upload)

            try:
                var_instance.save()
                upload.update(matchfile_vars_applied=True)
                make_log_entry(f"Updated Variable '{var_name}' and its attributes", "SUCCESS", upload=upload)
            except Exception as e:
                make_log_entry(f"On updating Variable instance '{var_name}' : {e}", "ERROR", upload=upload)
                upload.terminate()


