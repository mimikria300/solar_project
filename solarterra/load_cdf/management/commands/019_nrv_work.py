from django.core.management.base import BaseCommand
from spacepy import pycdf
import numpy as np
from load_cdf.models import *
from load_cdf.utils import safe_str
from .evaluate_extras import command_logger, UploadRequired


class Command(UploadRequired, BaseCommand):

    help = "#9 step in evaluation stage of the dataset upload. The command saves NRV variables into a separate table."

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    @command_logger
    def handle(self, *args, **options):

        upload = super().handle(**options)
        dataset = upload.dataset

        if dataset.nrv_data.exists():
            make_log_entry(f"NRV data for '{dataset.tag}' already exists ({dataset.nrv_data.count()} entries), skipping.", "FOUND", upload=upload)
            return

        nrv_variables = [v for v in dataset.variables.filter(dims__isnull=False).exclude(var_logic_type='ignore_data') if v.is_nrv()]

        if not nrv_variables:
            make_log_entry(f"Not found NRV variables for '{dataset.tag}'.", "INFO", upload=upload)
            return
        make_log_entry(f"Found {len(nrv_variables)} NRV variables to save.", "INFO", upload=upload)

        # NRV values ​​are the same in all files
        cdf_instance = CDFFileStored.objects.filter(upload=upload).first()
        if not cdf_instance:
            make_log_entry("Not found CDF files for this upload.", "ERROR", upload=upload)
            exit(1)

        cdf_obj = pycdf.CDF(cdf_instance.full_path)
        nrv_entries = []

        for variable in nrv_variables:
            var_name = variable.name

            if var_name not in cdf_obj:
                make_log_entry(f"NRV variable '{var_name}' not found in CDF file, skipping.", "WARNING", upload=upload)
                continue

            try:
                raw = cdf_obj[var_name][...]
            except Exception as e:
                make_log_entry(f"Could not read NRV variable '{var_name}': {e}", "WARNING", upload=upload)
                continue

            # numpy → python for JSON
            if isinstance(raw, np.ndarray):
                value = raw.tolist()
            elif hasattr(raw, 'item'):
                value = raw.item()
            else:
                value = raw

            # datatype work
            if variable.datatype:
                try:
                    data_type_instance = DataType.objects.get(cdf_file_label=variable.datatype)
                except:
                    make_log_entry(f"DataType instance for '{variable.name}' with cdf type '{variable.datatype}' is not supported", "ERROR", upload=upload)
                    exit(1)

            nrv_entries.append(NRVData(
                dataset=dataset,
                variable=variable,
                field_name=safe_str(var_name),
                value=value,
                data_type_instance=data_type_instance,
            ))

        cdf_obj.close()

        if nrv_entries:
            NRVData.objects.bulk_create(nrv_entries)
            upload.update(nrv_created=True)
            make_log_entry(f"Saved {len(nrv_entries)} NRV entries for '{dataset.tag}'.", "CREATED", upload=upload)
        else:
            make_log_entry(f"No NRV values extracted.", "WARNING", upload=upload)