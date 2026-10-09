from django.http import HttpResponse, StreamingHttpResponse
import io
import os
import zipfile
from django.db.models import Q
from load_cdf.models import Upload, CDFFileStored
from solarterra.utils import float_ts_resolver as ft
from solarterra.utils import ts_float_resolver as tf
import logging

logger = logging.getLogger('solarterra.export')

def find_cdf_files(variables, ts_start, ts_end):
    '''Stored CDF files overlapping the time range. 
    NB: Size check uses it too.'''
    valid_datasets = variables.values_list('dataset', flat=True).distinct()
    upload_instances = Upload.objects.filter(dataset__in=valid_datasets)

    tu_start = tf(ts_start)
    tu_end = tf(ts_end)

    # Filter the CDF file(s) based on time range overlap
    qs = CDFFileStored.objects.filter(upload__in=upload_instances).filter(
        Q(tu_start__gte=tu_start, tu_start__lte=tu_end)
        | Q(tu_end__gte=tu_start, tu_end__lte=tu_end)
        | Q(tu_start__lte=tu_start, tu_end__gte=tu_end)
    ).order_by('upload','tu_start')
    return qs


def raw_cdf_export(job):
    '''
    Export raw CDF files for the requested variables and time range as a zip archive.
    Returns a StreamingHttpResponse with the zipped CDF files.
    '''
    #TODO: CRUDE AF, raw_cdf shall have it's own ui endpoint
    qs = find_cdf_files(job.variables, job.ts_start, job.ts_end)

    logger.info(f"raw_cdf: found {qs.count()} CDF files to export")

    # Create zip file in memory (no temp disk files, no full copies of existing CDF files)
    # BytesIO holds the compressed data only — ZIP_DEFLATED compresses on-the-fly
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for cdf_file in qs:
            if os.path.exists(cdf_file.full_path):
                # arcname keeps only the filename in the archive (no full path)
                arcname = os.path.basename(cdf_file.full_path)
                zip_file.write(cdf_file.full_path, arcname=arcname)
                logger.debug(f"raw_cdf: added to zip {cdf_file.full_path}")
            else:
                logger.warning(f"raw_cdf: file not found {cdf_file.full_path}")
    
    # Rewind buffer to start for reading
    zip_buffer.seek(0)
    
    # Generate filename for the download
    zip_filename = f"cdf_export_{job.dt_str}.zip"
    
    # Return the zip file as a response
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    return response