from django.core.management.base import BaseCommand
from spacepy import pycdf
from load_cdf.models import *
from .evaluate_extras import command_logger, UploadRequired

class Command(UploadRequired, BaseCommand):

    help = "#3 step in evaluation stage of the dataset upload.\n\
            Command opens typical cdf file from the current dataset and saves its internal structure in corresponding models\n\
            Has undo counterpart undo_013 that deletes instances of DatasetAttribute, Variable and VariableAttribute"

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):
       
        upload = super().handle(**options)
        
        dataset = upload.dataset

        cdf_instance = CDFFileStored.objects.filter(upload=upload).first()
        cdf_obj = pycdf.CDF(cdf_instance.full_path)

        if upload.dataset_created:
            for xkey, xvalue in cdf_obj.attrs.items():
                upload.da_list.append(DatasetAttribute(
                    title=xkey,
                    value=xvalue,
                    dataset=dataset
                ))

            DatasetAttribute.objects.bulk_create(upload.da_list)
            upload.update(dataset_attributes_created=True)
            make_log_entry(f"Saved {len(upload.da_list)} instances of DatasetAttribute for {dataset.tag}", "CREATED", upload=upload)
        else:
            # compare attributes existing and about-to-be-saved by NAME ONLY and DO NOT SAVE the new ones, just output the difference and exit if there is

            new_attrs = set(cdf_obj.attrs.keys())
            existing_attrs = set(dataset.attributes.values_list('title', flat=True))
            diff_attrs =  new_attrs ^ existing_attrs
            if any(diff_attrs):
                make_log_entry(f"Dataset already exists, check shows difference in '{diff_attrs}' dataset attributes", "ERROR", upload=upload)
                upload.terminate()
            else:
                make_log_entry(f"Dataset already exists, check shows no difference in dataset attribute NAMES", "INFO", upload=upload)


        if upload.dataset_created:
            for var in cdf_obj.keys():
                upload.var_list.append(Variable(
                    name=var,
                    dataset=dataset
                ))
                for attr_title, attr_value in cdf_obj[var].attrs.items():
                    upload.var_attr_list.append(VariableAttribute(
                        title=attr_title,
                        value=attr_value,
                        variable=upload.var_list[-1]
                    ))

            Variable.objects.bulk_create(upload.var_list)
            make_log_entry(f"Saved {len(upload.var_list)} instances of Variable for {dataset.tag}", "CREATED", upload=upload)
            VariableAttribute.objects.bulk_create(upload.var_attr_list)
            make_log_entry(f"Saved {len(upload.var_attr_list)} instances of VariableAttribute for {dataset.tag}", "CREATED", upload=upload)
            upload.update(variables_created=True)

        else:
            new_vars = set(cdf_obj.keys())
            existing_vars = set(dataset.variables.values_list('name', flat=True))
            diff_vars = new_vars ^ existing_vars
            if any(diff_vars):
                make_log_entry(f"Dataset already exists, check shows difference in '{diff_vars}' dataset variables", "ERROR", upload=upload)
                upload.terminate()
            else:
                make_log_entry(f"Dataset already exists, check shows no difference in dataset variable NAMES", "INFO", upload=upload)
                # TODO: no checks for Variable attributes and no checks for the actual values difference

        
            
        del upload.da_list
        del upload.var_list
        del upload.var_attr_list

