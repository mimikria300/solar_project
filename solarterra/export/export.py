#lib import
from export.export_instances import Bin, DataHandler, PlainTextMeta

from load_cdf.models import DataType
from load_cdf.models import CDFFileStored, Variable, Dataset, Upload
from solarterra.utils import float_ts_resolver as ft
from solarterra.utils import ts_float_resolver as tf
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Q
import numpy as np
import datetime as dt
import tempfile, os, shutil, zipfile, io


def plain_text_generator(variables, ts_start, ts_end, aggregate=False, validate=False):
    '''
    Main streaming function to generate data for the given variables and time range.
    Yields header block and rows per dataset.

    NB: works in streaming mode.
    '''

    dataset = variables[0].dataset
    print(
        f"[EXPORT] IN plain_text_generator start. Dataset={dataset.tag}, "
        f"variables num={len(variables)}, ts_start={ts_start}, ts_end={ts_end}"
    )

    #CHECKPOINT: ptm poinking

    ptm = PlainTextMeta(variables)
    ptm.set_everything()
    ptm.info['aggregate'] = aggregate
    ptm.info['validate'] = validate
    ptm.info['ts_start'] = ts_start
    ptm.info['ts_end'] = ts_end

    # header
    yield from ptm.stream_header()
    #TODO: can render status from ptm info for debugging

    # build and run the query
    data = DataHandler(
        dataset=dataset,
        filter_field=ptm.depend_field,
        ts_start=ts_start,
        ts_stop=ts_end,
        fields=ptm.dyn_fields[1:]  # exclude depend field
    )
    data.query()
    #data.set_data()
    #data.test()  # debug print of data arrays and field info
    if not data.queryset.exists(): 
        print(f"[EXPORT] Query returned no rows for dataset={dataset.tag}")
        yield f"# No data for the specified time range {ts_start} to {ts_end}\n"
        yield from ptm.stream_footer()
        return
    
    data.set_data() #excecute query, now is in np.float64 #FIXME: in case of non-float\non-int types might fail; r we even do that?
    
    if validate:
        data.add_validation_to_mask()

    if aggregate:
        data.set_bin_arrays()  # creates bin_edges_array and bin_centers_array
        data.set_bin_map()  # creates bin id for each value
        ptm.info['bin_size'] = data.bin_instance.bin_seconds
        
        data.set_aggregated_data()
        rows = data.agg_data_by_record
         

    else:
        data.clean_data()  # mask invalid values with None, cast to numpy object
        rows = data.data_by_record

    yield from ptm.stream_label_rows()
    yield from ptm.stream_formatted_rows(rows)
    yield from ptm.stream_footer()


def plain_text_stream(ptm, rows):
    '''
    Streaming formatter for pre-loaded, pre-processed data.
    Use when the data pipeline runs in the caller (e.g. to resolve actual filename before streaming starts).

    ptm: PlainTextMeta instance with info already fully set.
    rows: numpy record array (data_by_record or agg_data_by_record), or None if no data in range.
    '''
    yield from ptm.stream_header()
    if rows is None:
        yield f"# No data for the specified time range {ptm.info['ts_start']} to {ptm.info['ts_end']}\n"
        yield from ptm.stream_footer()
        return
    yield from ptm.stream_label_rows()
    yield from ptm.stream_formatted_rows(rows)
    yield from ptm.stream_footer()


def single_file_export(dataset, var_group, ts_start, ts_end, aggregate, validate, dt_str, mode_tag):
    '''
    Build the ptm/data pipeline for one variable group and stream it back as a single plain-text file.
    Returns a StreamingHttpResponse ready to hand back from the view.
    '''
    ptm = PlainTextMeta(var_group)
    ptm.set_everything()
    ptm.info['aggregate'] = aggregate
    ptm.info['validate'] = validate
    ptm.info['ts_start'] = ts_start
    ptm.info['ts_end'] = ts_end

    data = DataHandler(
        dataset=dataset,
        filter_field=ptm.depend_field,
        ts_start=ts_start,
        ts_stop=ts_end,
        fields=ptm.dyn_fields[1:]
    )
    data.query()

    if not data.queryset.exists():
        rows = None
        file_dt_str = dt_str
    else:
        data.set_data()
        if validate:
            data.add_validation_to_mask()
        if aggregate:
            data.set_bin_arrays()
            data.set_bin_map()
            ptm.info['bin_size'] = data.bin_instance.bin_seconds
            data.set_aggregated_data()
            if data.agg_data_by_record.shape[0] == 0:
                rows = None
                file_dt_str = dt_str
            else:
                actual_start = ft(int(data.agg_data_by_var[0][0]))
                actual_end = ft(int(data.agg_data_by_var[0][-1]))
                file_dt_str = actual_start.strftime('%Y%m%d%H%M') + '_' + actual_end.strftime('%Y%m%d%H%M')
                rows = data.agg_data_by_record
        else:
            data.clean_data()
            file_dt_str = dt_str
            rows = data.data_by_record

    filename = f"{file_dt_str}_{dataset.tag}_{var_group[0].depend_0}_{mode_tag}.txt"

    print(f"[EXPORT] Single file streaming. Dataset: {dataset.tag}, depend_0: {var_group[0].depend_0}")
    print(f"[EXPORT] Streaming plain text file for dataset={dataset.tag}, depend_0={var_group[0].depend_0}, variables={len(var_group)}")

    response = StreamingHttpResponse(
        plain_text_stream(ptm, rows),
        content_type="text/plain",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def multi_file_export(variables, var_groups, ts_start, ts_end, aggregate, validate, dt_str, mode_tag):
    '''
    Export each variable group as its own plain-text file, zipped together.
    Returns an HttpResponse with the zip archive attached.
    '''
    print(f"[EXPORT] Multiple variable groups detected. Exporting each group as a separate file, expected filecount: {len(var_groups)}")
    zip_timestamp = dt.datetime.now().strftime("%Y-%d-%m-%H-%M")
    zip_filename = f"exported_data_{zip_timestamp}.zip"
    with tempfile.TemporaryDirectory() as temp_dir:
        export_dir = os.path.join(temp_dir, "exported_data")
        os.makedirs(export_dir, exist_ok=True)

        print(f"[EXPORT] Temp export dir: {export_dir}")

        for item in var_groups:
            print(f"[EXPORT] Processing variable group: {item.dataset.tag} {item.depend_0}")
            var_group = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')

            ptm = PlainTextMeta(var_group)
            ptm.set_everything()
            ptm.info['aggregate'] = aggregate
            ptm.info['validate'] = validate
            ptm.info['ts_start'] = ts_start
            ptm.info['ts_end'] = ts_end

            data = DataHandler(
                dataset=item.dataset,
                filter_field=ptm.depend_field,
                ts_start=ts_start,
                ts_stop=ts_end,
                fields=ptm.dyn_fields[1:]
            )
            data.query()

            if not data.queryset.exists():
                rows = None
                file_dt_str = dt_str
            else:
                data.set_data()
                if validate:
                    data.add_validation_to_mask()
                if aggregate:
                    data.set_bin_arrays()
                    data.set_bin_map()
                    ptm.info['bin_size'] = data.bin_instance.bin_seconds
                    data.set_aggregated_data()
                    if data.agg_data_by_record.shape[0] == 0:
                        rows = None
                        file_dt_str = dt_str
                    else:
                        actual_start = ft(int(data.agg_data_by_var[0][0]))
                        actual_end = ft(int(data.agg_data_by_var[0][-1]))
                        file_dt_str = actual_start.strftime('%Y%m%d%H%M') + '_' + actual_end.strftime('%Y%m%d%H%M')
                        rows = data.agg_data_by_record
                else:
                    data.clean_data()
                    file_dt_str = dt_str
                    rows = data.data_by_record

            filename = f"{file_dt_str}_{item.dataset.tag}_{item.depend_0}_{mode_tag}.txt"
            filepath = os.path.join(export_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as file_handle:
                for line in plain_text_stream(ptm, rows):
                    file_handle.write(line)

            print(f"[EXPORT] Wrote file: {filepath}")

        archive_base = os.path.join(temp_dir, "exported_data")
        resulting_zip_path = shutil.make_archive(archive_base, 'zip', export_dir)

        print(f"[EXPORT] Zip created: {resulting_zip_path}")

        with open(resulting_zip_path, 'rb') as zip_handle:
            zip_bytes = zip_handle.read()

        print(f"[EXPORT] Zip size in bytes: {len(zip_bytes)}")

    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
    response["Content-Length"] = len(zip_bytes)
    return response

def export_dispatcher(request):
    '''
    Main entry point for export requests.
    Determines the export mode based on the request parameters and calls the appropriate function.
    '''
    # Extract parameters from request (e.g., dataset, variables, time range, aggregate, validate)
    # Determine if single file or multi-file export is needed
    # Call single_file_export or multi_file_export accordingly
    pass

def raw_cdf_export(selected_missions, variables, ts_start, ts_end):
    '''
    Export raw CDF files for the requested variables and time range as a zip archive.
    Returns a StreamingHttpResponse with the zipped CDF files.
    '''
    # Extract parameters from request (e.g., dataset, variables, time range)
    #TODO: CRUDE AF, raw_cdf shall have it's own ui endpoint
    valid_datasets = set(var.dataset for var in variables)
    upload_instances = Upload.objects.filter(dataset__in=valid_datasets)

    tu_start = tf(ts_start)
    tu_end = tf(ts_end)

    # Filter the CDF file(s) based on time range overlap
    qs = CDFFileStored.objects.filter(upload__in=upload_instances).filter(
        Q(tu_start__gte=tu_start, tu_start__lte=tu_end)
        | Q(tu_end__gte=tu_start, tu_end__lte=tu_end)
        | Q(tu_start__lte=tu_start, tu_end__gte=tu_end)
    ).order_by('upload','tu_start')
    
    print(f"[EXPORT] raw_cdf: found {qs.count()} CDF files to export")

    # Create zip file in memory (no temp disk files, no full copies of existing CDF files)
    # BytesIO holds the compressed data only — ZIP_DEFLATED compresses on-the-fly as we add files
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for cdf_file in qs:
            if os.path.exists(cdf_file.full_path):
                # arcname keeps only the filename in the archive (no full path)
                arcname = os.path.basename(cdf_file.full_path)
                zip_file.write(cdf_file.full_path, arcname=arcname)
                print(f"[EXPORT] Added to zip: {cdf_file.full_path}")
            else:
                print(f"[EXPORT] Warning: file not found: {cdf_file.full_path}")
    
    # Rewind buffer to start for reading
    zip_buffer.seek(0)
    
    # Generate filename for the download
    ts_start_str = ts_start.strftime('%Y%m%d%H%M')
    ts_end_str = ts_end.strftime('%Y%m%d%H%M')
    zip_filename = f"cdf_export_{ts_start_str}_{ts_end_str}.zip"
    
    # Return the zip file as a response
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    return response