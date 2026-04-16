from load_cdf.models import DynamicField, DataType
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import NOW
import numpy as np
import datetime

from pages.datawork_instances import Bin, DBQuery

GLOBAL_ATTRIBUTE_MAP = [
    ("MISSION", "mission"),
    ("SOURCE_NAME", "source_name"),
    ("DATA_TYPE", "data_type"),
    ("INSTRUMENT", "instrument"),
    ("DATASET_VERSION", "dataset_version"),
    ("TEXT_DESCRIPTION", "text_description"),
    ("LOGICAL_SOURCE", "logical_source"),
    ("LOGICAL_DESCRIPTION", "logical_description"),
    ("PI_NAME", "pi_name"),
    ("PI_AFFILIATION", "pi_affiliation"),
]


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

    # Yield header block for this dataset
    yield from _header_builder(variables, dataset)

    # Yield data table (labels + rows) for this dataset
    yield from _table_builder(variables, dataset, ts_start, ts_end, aggregate, validate)

    yield f"# End of data in the chosen interval for the dataset: {dataset.tag}\nFile generated at {NOW()}"

def _header_builder(variables, dataset):
    '''Header block for one file.'''

    depend_var = variables[0].get_depend_var()
    described_variables = list(variables)
    if depend_var is not None and all(var.id != depend_var.id for var in described_variables):
        described_variables = [depend_var] + described_variables

    # not a tuple, python convention for readability
    ga = (
        '#              ************************************\n'
        '#              *****    GLOBAL ATTRIBUTES    ******\n'
        '#              ************************************\n'
        '#\n'
    )

    mf_str = _render_global_attributes(dataset)

    rvv = (
        '#              ************************************\n'
        '#              ****  RECORD VARYING VARIABLES  ****\n'
        '#              ************************************\n'
        '#\n'
    )

    var_desc = ''
    for i, var in enumerate(described_variables,1):
        catdesc = var.catdesc
        var_desc += f'#   {i}. {catdesc}\n'

    var_desc += '#\n'

    yield ga + mf_str + rvv + var_desc


def _render_global_attributes(dataset):
    title_map = {}
    for attr in dataset.attributes.filter(linked_standard_field__isnull=False):
        standard_key = attr.linked_standard_field.upper()
        if standard_key not in title_map:
            title_map[standard_key] = attr.title

    lines = []
    for standard_key, dataset_field in GLOBAL_ATTRIBUTE_MAP:
        value = getattr(dataset, dataset_field, None)
        if value is None or value == "":
            continue

        original_name = title_map.get(standard_key)
        label = f"{standard_key} ({original_name})" if original_name else standard_key

        value_lines = str(value).splitlines()
        if not value_lines:
            continue

        lines.append(f"#     {label}: {value_lines[0]}\n")
        for extra_line in value_lines[1:]:
            lines.append(f"#     {extra_line}\n")

    lines.append('#\n')
    return ''.join(lines)


def _table_builder(variables, dataset, ts_start, ts_end, aggregate=False, validate=False):

    depend_field = variables[0].get_depend_field()

    #CHECKPOINT query building

    # Get all field names ordered by variable name then component index to match header
    dyn_fields_q = DynamicField.objects.filter(variable_instance__in=variables).order_by('variable_instance__name', 'multipart_index')
    dyn_fields = list(dyn_fields_q.all())
    fields = [df.field_name for df in dyn_fields]
    print(
        f"[EXPORT] in _table_builder. dataset={dataset.tag}, depend_field={depend_field.field_name}, "
        f"dynamic_fields={dyn_fields}"
    )
    # prepend epoch/depend field so labels, units, formats, colwidths align with record_arrays column order
    # epoch isn't added to fields which are passed to query because it will be added as the filter_field in the query
    dyn_fields = [depend_field] + dyn_fields

    query = DBQuery(
        dataset=dataset,
        filter_field=depend_field.field_name,
        t_start=ts_start,
        t_stop=ts_end,
        fields=fields
    )

    query.query()

    #CHECKPOINT getting labels and units

    labels = ['Epoch']
    units = ['dd-mm-yyyy hh:mm:ss.ms']
    for df in dyn_fields[1:]:
        var_instance = df.variable_instance
        print(df.field_name)
        if df.multipart:
            label = var_instance.lablaxis[df.multipart_index - 1]
            #it happens so that some variables have a single unit for all components, not a list with repeated one
            if isinstance(var_instance.units, str):
                unit = var_instance.units
            else:
                unit = var_instance.units[df.multipart_index - 1]
        else:
            label = var_instance.lablaxis
            unit = var_instance.units
        labels.append(label if label is not None else '')
        units.append(unit if unit is not None else '')


    #CHECKPOINT getting formats and DataType instances

    type_and_format_pairs = []
    for df in dyn_fields:
        var_instance = df.variable_instance
        if df.multipart:
            #it happens so that some variables have a single format for all components, not a list with repeated one
            if isinstance(var_instance.output_format, str):
                format_str = var_instance.output_format
            else:
                format_str = var_instance.output_format[df.multipart_index - 1]
        else:
            format_str = var_instance.output_format
        type_instance = var_instance.get_data_type_instance()
        type_and_format_pairs.append((type_instance, format_str))

    #CHECKPOINT building format map
    format_map = _format_map_builder(type_and_format_pairs)

    #CHECKPOINT building colwidths
    colwidths = []
    for label, tf_pair, unit in zip(labels, type_and_format_pairs, units):
        cw = max(len(label), len(unit))
        type_instance, format_str = tf_pair
        if type_instance.is_epoch():
            cw = max(cw, len("dd-mm-yyyy hh:mm:ss.ms"))
        elif format_str is not None and "i" in format_str.lower():
            cw = max(cw, int(format_str.lower().strip("i")))
        elif format_str is not None and "f" in format_str.lower():
            #print("FLOAT FORMAT STR", format_str, label, unit)
            cw = max(cw, int(format_str.lower().strip("f").split(".")[0]))
        elif format_str is not None and "e" in format_str.lower():
            cw = max(cw, int(format_str.lower().strip("e").split(".")[0]) + 5)
        else:
            #would be nice to evaluate the length of the string based on the actual data
            cw = max(cw, 10)
        colwidths.append(cw+5) #+5 for padding
    if not query.queryset.exists():
        print(f"[EXPORT] Query returned no rows for dataset={dataset.tag}")
        yield f"# No data for the specified time range {ts_start} to {ts_end}\n"
        return

    if not aggregate:
        query.set_record_arrays()
        rows = query.record_arrays
        print(f"[EXPORT] Query returned rows: {query.get_record_count()}")

        if validate and rows is not None:
            # filter out values outside validmin/validmax — blanks them in the output
            _apply_validation_to_records(rows, dyn_fields[1:])

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
                var_array = _validate_array(var_array, dyn_fields[i + 1])
            agg_cols.append(_aggregate_var_array(var_array, query.bin_map, bin_centers_array.shape[0]))

        rows = np.stack(agg_cols, axis=1)

        print(
            f"[EXPORT] Aggregation prep ready. rows={query.get_var_array_len()}, "
            f"bin_seconds={bin_instance.bin_seconds}, bins={bin_starts_array.shape[0]}, "
            f"aggregated_rows={rows.shape[0]}"
        )

    yield from _label_row_builder(labels, units, colwidths)
    yield from _row_generator(rows, format_map, colwidths)


def _label_row_builder(labels, units, colwidths):
    lblrow = ['#']
    unitrow = ['#']
    for label, unit, cw in zip(labels, units, colwidths):
        lblrow.append(' '*(cw - len(label)) + label)
        unitrow.append(' '*(cw - len(unit)) + unit)

    yield "".join(lblrow) + "\n"
    yield "".join(unitrow) + "\n"

def _row_generator(rows, format_map, colwidths):

    # arrays[0] = timestamps, arrays[1:] = field values in same order as fields
    for row in rows:
        yield _row_formatter(row, format_map, colwidths)


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


def _row_formatter(row, format_map, colwidths):
    '''format map application to a row, then conversion to CSV string.'''

    formatted_row = [" "] #to correct first column padding to the # symbol in labels
    for value, formatter, cw in zip(row, format_map, colwidths):
        formatted_value = formatter(value)
        # add padding based on colwidth
        formatted_value = ' '*(cw - len(formatted_value)) + formatted_value
        formatted_row.append(formatted_value)

    return "".join(formatted_row) + "\n"

def _format_map_builder(type_and_format_pairs):
    '''Build a list of formatter functions corresponding to the fields.'''

    format_map = []
    for type_instance, format_str in type_and_format_pairs:

        #CHECKPOINT pasrse format_str and build formatter function

        formatter = make_format_function(type_instance, format_str)
        format_map.append(formatter)

    return format_map

#might be generated for the dynamic field and stored there for formatting consistency!
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

