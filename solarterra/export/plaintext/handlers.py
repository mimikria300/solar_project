# Response building for plaintext export

#lib import
from export.data_processing import Bin, DataHandler
from export.plaintext.formatting import PlainTextMeta

from load_cdf.models import DataType
from load_cdf.models import CDFFileStored, Variable, Dataset, Upload
from solarterra.utils import float_ts_resolver as ft
from solarterra.utils import ts_float_resolver as tf
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Q
import numpy as np
import datetime as dt
import tempfile, os, shutil, zipfile, io
import logging

logger = logging.getLogger('solarterra.export')

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


def _process_single_group(job, dataset, var_group):
    '''
    Build the ptm/data pipeline for one variable group (shared by single_file_export and multi_file_export).
    Returns (ptm, rows, file_dt_str) — rows is None when there's no data in range, in which case file_dt_str falls back to dt_str.

    job.dt_str is the requested ts_start/ts_end range, formatted for use in a filename.
    file_dt_str is what actually goes in the filename: normally same as dt_str, overwritten when aggregating: aggregation bins may differ
    '''
    ptm = PlainTextMeta(var_group)
    ptm.set_everything()
    ptm.info['aggregate'] = job.aggregate
    ptm.info['validate'] = job.validate
    ptm.info['ts_start'] = job.ts_start
    ptm.info['ts_end'] = job.ts_end

    data = DataHandler(
        dataset=dataset,
        filter_field=ptm.depend_field,
        ts_start=job.ts_start,
        ts_stop=job.ts_end,
        fields=ptm.dyn_fields[1:]
    )
    data.query()

    if not data.queryset.exists():
        return ptm, None, job.dt_str

    data.set_data()
    if job.validate:
        data.add_validation_to_mask()

    if job.aggregate:
        data.set_bin_arrays()  # creates bin_edges_array and bin_centers_array
        data.set_bin_map()  # creates bin id for each value
        ptm.info['bin_size'] = data.bin_instance.bin_seconds
        data.set_aggregated_data()
        if data.agg_data_by_record.shape[0] == 0:
            return ptm, None, job.dt_str
        # actual data range replaces the requested range in the filename (see docstring above)
        actual_start = ft(int(data.agg_data_by_var[0][0]))
        actual_end = ft(int(data.agg_data_by_var[0][-1]))
        file_dt_str = actual_start.strftime('%Y%m%d%H%M') + '_' + actual_end.strftime('%Y%m%d%H%M')
        return ptm, data.agg_data_by_record, file_dt_str

    data.clean_data()
    return ptm, data.data_by_record, job.dt_str


def single_file_export(job, dataset, var_group):
    '''
    Build the ptm/data pipeline for one variable group and stream it back as a single plain-text file.
    Returns a StreamingHttpResponse ready to hand back from the view.
    '''
    ptm, rows, real_dt_str = _process_single_group(job, dataset, var_group)

    filename = f"{dataset.tag}_{var_group[0].depend_0}_{job.mode_tag}_{real_dt_str}.txt"

    logger.info(f"plaintext: streaming {filename}, variables={len(var_group)}")

    response = StreamingHttpResponse(
        plain_text_stream(ptm, rows),
        content_type="text/plain",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def multi_file_export(job, var_groups):
    '''
    Export each variable group as its own plain-text file, zipped together.
    Returns an HttpResponse with the zip archive attached.
    '''
    logger.info(f"plaintext: {len(var_groups)} variable groups -> one file each, zipped")
    zip_timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")
    zip_filename = f"exported_data_{zip_timestamp}.zip"
    with tempfile.TemporaryDirectory() as temp_dir:
        export_dir = os.path.join(temp_dir, "exported_data")
        os.makedirs(export_dir, exist_ok=True)

        logger.debug(f"plaintext: temp export dir {export_dir}")

        for item in var_groups:
            logger.debug(f"plaintext: processing group {item.dataset.tag} {item.depend_0}")
            var_group = job.group_vars(item)

            ptm, rows, real_dt_str = _process_single_group(job, item.dataset, var_group)

            filename = f"{item.dataset.tag}_{item.depend_0}_{job.mode_tag}_{real_dt_str}.txt"
            filepath = os.path.join(export_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as file_handle:
                for line in plain_text_stream(ptm, rows):
                    file_handle.write(line)

            logger.debug(f"plaintext: wrote {filepath}")

        archive_base = os.path.join(temp_dir, "exported_data")
        resulting_zip_path = shutil.make_archive(archive_base, 'zip', export_dir)

        logger.debug(f"plaintext: zip created {resulting_zip_path}")

        with open(resulting_zip_path, 'rb') as zip_handle:
            zip_bytes = zip_handle.read()

        logger.info(f"plaintext: zip {zip_filename}, {len(zip_bytes)} bytes")

    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
    response["Content-Length"] = len(zip_bytes)
    return response