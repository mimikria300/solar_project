from load_cdf.models import DataType
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
import numpy as np
import datetime

from pages.datawork_instances import Bin, DBQuery, PlainTextFile


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

    ptf = PlainTextFile(variables, dataset)
    ptf.set_labels_and_units()
    ptf.set_type_and_format_pairs()
    ptf.set_format_map()
    ptf.set_colwidths()

    # header
    yield from ptf.generate_header()

    # build and run the query
    query = DBQuery(
        dataset=dataset,
        filter_field=ptf.depend_field.field_name,
        t_start=ts_start,
        t_stop=ts_end,
        fields=ptf.field_names_for_query
    )
    query.query()

    if not query.queryset.exists():
        print(f"[EXPORT] Query returned no rows for dataset={dataset.tag}")
        yield f"# No data for the specified time range {ts_start} to {ts_end}\n"
        yield from ptf.generate_footer()
        return

    if not aggregate:
        query.set_record_arrays()
        rows = query.record_arrays
        print(f"[EXPORT] Query returned rows: {query.get_record_count()}")

        if validate and rows is not None:
            # filter out values outside validmin/validmax — blanks them in the output
            _apply_validation_to_records(rows, ptf.dyn_fields[1:])

    else:

        query.set_var_arrays()
        bin_instance = Bin(ts_start, ts_end)
        i_start = ti(ts_start)
        i_stop = ti(ts_end)
        
        #extended for the last bin to be calculated properly
        bin_starts_array = np.arange(
            i_start,
            i_stop + (bin_instance.bin_seconds * 2),
            step=bin_instance.bin_seconds,
        )
        bin_centers_array = bin_starts_array + (bin_instance.half_bin)
        query.set_bin_map(bin_starts_array)

        agg_cols = [bin_centers_array]
        for i, var_array in enumerate(query.var_arrays[1:]):
            # NaN out-of-range values before aggregation so they don't affect bin means
            if validate:
                var_array = _validate_array(var_array, ptf.dyn_fields[i + 1])
            agg_cols.append(_aggregate_var_array(var_array, query.bin_map, bin_centers_array.shape[0]))

        rows = np.stack(agg_cols, axis=1)

        print(
            f"[EXPORT] Aggregation prep ready. rows={query.get_var_array_len()}, "
            f"bin_seconds={bin_instance.bin_seconds}, bins={bin_starts_array.shape[0]}, "
            f"aggregated_rows={rows.shape[0]}"
        )

    yield from ptf.generate_label_rows()
    yield from ptf.generate_rows(rows)
    yield from ptf.generate_footer()


def _get_bounds(variable, dyn_field):
    '''Resolve validmin/validmax for a single dynamic field, accounting for multipart variables.'''
    vmin = variable.validmin
    if vmin is not None and dyn_field.multipart and isinstance(vmin, list):
        vmin = vmin[dyn_field.multipart_index - 1]
    vmax = variable.validmax
    if vmax is not None and dyn_field.multipart and isinstance(vmax, list):
        vmax = vmax[dyn_field.multipart_index - 1]
    return vmin, vmax


def _validate_array(arr, dyn_field):
    '''Return a copy of arr with out-of-bounds values set to NaN.
    Used in the aggregated export path: _aggregate_var_array already skips NaNs,
    so this effectively excludes invalid points from bin means.'''
    var = dyn_field.variable_instance
    vmin_raw, vmax_raw = _get_bounds(var, dyn_field)
    if vmin_raw is None and vmax_raw is None:
        return arr

    result = np.array(arr, dtype=float)
    non_nan = ~np.isnan(result)
    if not non_nan.any():
        return result
    # need a real sample value to cast the string bound to the right numpy type
    sample = result[non_nan][0]

    if vmin_raw is not None:
        bound = DataType.proper_type(vmin_raw, sample)
        if bound is not None:
            result[result < bound] = np.nan
    if vmax_raw is not None:
        bound = DataType.proper_type(vmax_raw, sample)
        if bound is not None:
            result[result > bound] = np.nan
    return result


def _apply_validation_to_records(rows, data_dyn_fields):
    '''Validate the non-aggregated record_arrays in-place.
    Sets out-of-bounds cells to None so the row formatter renders them as blank.
    Iterates over data columns (skipping col 0 = epoch).'''
    for col_idx, df in enumerate(data_dyn_fields, start=1):
        var = df.variable_instance
        vmin_raw, vmax_raw = _get_bounds(var, df)
        if vmin_raw is None and vmax_raw is None:
            continue

        col = rows[:, col_idx]
        # cast column to float for numeric comparison
        float_col = np.array(col, dtype=float)
        non_nan = ~np.isnan(float_col)
        if not non_nan.any():
            continue
        # need a sample to cast the string bound via DataType.proper_type
        sample = float_col[non_nan][0]

        invalid = np.zeros(len(col), dtype=bool)
        if vmin_raw is not None:
            bound = DataType.proper_type(vmin_raw, sample)
            if bound is not None:
                invalid |= float_col < bound
        if vmax_raw is not None:
            bound = DataType.proper_type(vmax_raw, sample)
            if bound is not None:
                invalid |= float_col > bound

        if invalid.any():
            rows[:, col_idx] = np.where(invalid, None, col)


def _aggregate_var_array(var_array, bin_map, bin_count):
    var_array = np.asarray(var_array)
    mask = ~np.isnan(var_array)

    val_bin_map = bin_map[mask] - 1
    val_array = var_array[mask].astype(float)

    valid_mask = (val_bin_map >= 0) & (val_bin_map < bin_count)
    val_bin_map = val_bin_map[valid_mask]
    val_array = val_array[valid_mask]

    result = np.full(bin_count, np.nan)
    if val_bin_map.shape[0] == 0:
        return result

    order = np.argsort(val_bin_map)
    val_bin_map = val_bin_map[order]
    val_array = val_array[order]

    idx, pos, counts = np.unique(val_bin_map, return_index=True, return_counts=True)
    sums = np.add.reduceat(val_array, pos)
    means = sums / counts
    result[idx] = means
    return result
        

#might be generated for each dynamic field instance and stored there for formatting consistency!
def make_format_function(type_instance, format_str):
    '''Factory for field-specific formatter functions.'''
    
    if type_instance.is_epoch():
        #nb: the current uploader is ommiting milliseconds completely (it rounds the timestamps to seconds)
        return lambda x: it(x).strftime("%Y-%m-%d %H:%M:%S") + f"-{it(x).microsecond // 1000:03d}" if x is not None else ""
    elif format_str is not None and "i" in format_str.lower():
        #it is usually for year/day/etc, doesn't really need to be zero-padded; added as a place to add different bechavior for int types if needed
        return lambda x: str(x) if x is not None else ""
    elif format_str is not None and "f" in format_str.lower():
        return lambda x: f"{x:{format_str.lower().strip('f')}f}" if x is not None else ""
    elif format_str is not None and "e" in format_str.lower():
        #scientific float formatter
        return lambda x: f"{x:{format_str.lower().strip('e')}e}" if x is not None else ""
    else:
        #fallback
        return lambda x: str(x) if x is not None else ""

def clean_cdf_generator(variables, ts_start, ts_end, aggregate=False, validate=False):
    pass