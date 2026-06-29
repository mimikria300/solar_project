#lib import
from pages.export_instances import Bin, DataHandler, PlainTextMeta

from load_cdf.models import DataType
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
import numpy as np


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