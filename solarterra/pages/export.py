from load_cdf.models import DynamicField
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
import numpy as np
from pages.db_query import DBQuery

def csv_generator(variables, ts_start, ts_end):
    '''
    Main streaming function to generate CSV data for the given variables and time range.
    Yields header block and rows per dataset.
    '''
    
    for item in variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'):
        vars_in_dataset = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')
        
        if item.depend_0 is None:
            print(f"No dependent axis specified for dataset '{item.dataset}'! Skipping")
            continue
        
        # Yield header block for this dataset
        yield from _header_for_dataset(item.dataset, vars_in_dataset)
        
        # Yield rows for this dataset
        for row in _row_generator(vars_in_dataset, item.dataset, item.get_depend_field().field_name, ts_start, ts_end):
            yield _row_formatter(row)
        
        # Blank line between blocks
        yield "\n"

def _header_for_dataset(dataset, variables):
    '''Header block for one dataset.'''
    yield f"# Dataset: {dataset.tag}\n"
    cols = ["timestamp"]
    for var in variables:
        dyn_fields = var.dynamic.order_by('multipart_index')
        if dyn_fields.count() == 1:
            cols.append(var.name)
        else:
            for df in dyn_fields:
                cols.append(f"{var.name}_{df.multipart_index}")
    yield ",".join(cols) + "\n"

def _row_generator(variables, dataset, filter_field, ts_start, ts_end):
    '''
    Generator that yields [timestamp, value1, value2, ...] rows for one dataset.
    One row per timestamp with all variable values.
    '''
    
    # Get all field names ordered by variable name then component index to match header
    fields = list(
        DynamicField.objects
        .filter(variable_instance__in=variables)
        .order_by('variable_instance__name', 'multipart_index')
        .values_list('field_name', flat=True)
    )
    
    query = DBQuery(
        dataset=dataset,
        filter_field=filter_field,
        t_start=ts_start,
        t_stop=ts_end,
        fields=fields
    )
    
    query.query()
    
    if query.queryset.exists():
        query.set_arrays()
        
        # arrays[0] = timestamps, arrays[1:] = field values in same order as fields
        timestamps = query.arrays[0]
        
        # Yield one row per timestamp with all values
        for i, ts in enumerate(timestamps):
            row = [int(ts)]
            for field_idx in range(len(fields)):
                value = query.arrays[field_idx + 1][i]
                row.append(value)
            yield row

def _row_formatter(row):
    '''Format a row as CSV string.'''
    return ",".join([str(item) for item in row]) + "\n"

#SQUIRREL: verification of empty or non-significant data -> to the plan 
#SQUIRREL #HUH shall we limit a file to a single dataset? or allow multiple datasets in a single export?
#SQUIRREL: i want to have a "park squirrels" prompt for zero