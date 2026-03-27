from load_cdf.models import DynamicField
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
import numpy as np

#SQUIRREL: i may want to do the architecture as it is in plotting: two different files -
# exporting.py for calling export for different options and export_instances.py for building query and headers and format maps
# i mean, underscore functions clearly could be organized as class methods, and it's easier to pass objects around
# tho it ruins stream approach, isn't it? unless we add a write() method for data_table class and call it instead of using Echo

#note: yes it is a copy of db query from plotting, but the export and plotting are two separate modules and i want to keep them that way
class DBQuery:
    def __init__(self, dataset, filter_field, t_start, t_stop, fields):
        # instance
        self.dataset = dataset
        # class
        self.data_class = dataset.dynamic.resolve_class()

        # time strings
        self.start_limit = ti(t_start)
        self.stop_limit = ti(t_stop)

        # field (instance) on which the filtering happens
        self.filter_field = filter_field
        self.fields = fields
        # 0th position of the filter_field is important
        self.all_fields = [filter_field] + fields

        # not evaluated queryset
        self.queryset = None
        # transposed and sorted arrays of values
        self.var_arrays = None
        # sorted arrays of records (timestamp + values)
        self.record_arrays = None

        # bin mapping over over the array of epochs
        self.bin_map = None

    def query(self):
        kwargs = {
            "{0}__gte".format(self.filter_field): self.start_limit,
            "{0}__lte".format(self.filter_field): self.stop_limit,
        }
        self.queryset = self.data_class.objects.filter(**kwargs)

    def set_var_arrays(self):

        '''
        Executes queryset, outputs in format:
        arrays[0] = timestamps, arrays[1:] = field values in same order as fields

        epoch array
        field value array 1
        field value array 2
        ...

        Used in plotting.
        '''

        # if queryset is not completely empty
        if self.queryset.exists():
            rows = self.queryset.values_list(*self.all_fields)
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            # sort everythong by the first row
            sorted_pile = pile[pile[:, 0].argsort()]

            # transpose to form arrays
            self.var_arrays = sorted_pile.T

    def set_record_arrays(self):

        '''
        Executes queryset, outputs in format:
        rows[0] = [timestamp, value1, value2, ...]
        rows[1] = [timestamp, value1, value2, ...]
        ...


        Used in export.
        '''
        # if queryset is not completely empty
        if self.queryset.exists():

            rows = self.queryset.values_list(*self.all_fields)
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            # sort everythong by the first row
            sorted_pile = pile[pile[:, 0].argsort()]

            self.record_arrays = sorted_pile

    def get_var_array_len(self):
        if self.var_arrays is not None:
            return self.var_arrays[0].shape[0]
        #maybe u shouldn't call this if var_arrays is None but record_arrays is not None, but just in case
        elif self.record_arrays is not None:
            return self.record_arrays.shape[0]

    def get_record_count(self):
        if self.record_arrays is not None:
            return self.record_arrays.shape[0]
        elif self.var_arrays is not None:
            return self.var_arrays[0].shape[0]

    def get_full_time_array(self):
        if self.var_arrays is not None:
            return self.var_arrays[0]
        elif self.record_arrays is not None:
            return self.record_arrays[:, 0]

    def set_bin_map(self, bin_starts_array):
        # ANNOTATION: Map each timestamp to the insertion index of its right-side bin boundary.
        self.bin_map = np.searchsorted(bin_starts_array, self.get_full_time_array(), side="right")

def export_handler(variables):
    #might as well be inside the export view
    pass

def csv_generator(variables, ts_start, ts_end): #AKA single file generator. it actually may be packed into the class init
    '''
    Main streaming function to generate CSV data for the given variables and time range.
    Yields header block and rows per dataset.

    NB: works in streaming mode.
    May later be changed for small data queres and left with a streaming version for bigger ones.
    '''
    #currently doesnt support multiple files duh, item is actually a  var group for a separate file
    for item in variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'):
        var_group = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')

        print(f"[EXPORT] Processing dataset: {item.dataset.tag}, depend_0: {item.depend_0}")

        if item.depend_0 is None:
            print(f"No dependent axis specified for dataset '{item.dataset}'! Skipping")
            continue

        # Yield header block for this dataset
        #FIXME shall be not yielded, i want a plain return
        # the generator MIGHT yield it row but row but the header-gen must give out the whole header at a time
        yield from _header_builder(item.dataset, var_group)

        # Yield data table (labels + rows) for this dataset
        yield from _table_builder(var_group, item.dataset, item.get_depend_field().field_name, ts_start, ts_end)

        #TODO: make a footer builder with the OKAY/NOT OKAY flag
        #yield footer
        yield f"# End of dataset: {item.dataset.tag}\nSuccess! ✨\n"

def _header_builder(dataset, variables):
    '''Header block for one file.'''
    yield f"# Dataset: {dataset.tag}\n"


def _table_builder(variables, dataset, filter_field, ts_start, ts_end):

    #CHECKPOINT query building

    # Get all field names ordered by variable name then component index to match header
    dyn_fields_q = DynamicField.objects.filter(variable_instance__in=variables).order_by('variable_instance__name', 'multipart_index')
    dyn_fields = list(dyn_fields_q.all())
    fields = [df.field_name for df in dyn_fields]

    query = DBQuery(
        dataset=dataset,
        filter_field=filter_field,
        t_start=ts_start,
        t_stop=ts_end,
        fields=fields
    )

    query.query()

    #CHECKPOINT building format map
    format_map, colwidths = _format_map_builder(dyn_fields)

    #CHECKPOINT building label row (colwidth applies)


    yield from _row_generator(query, ts_start, ts_end, format_map=format_map)

def _get_labels(dynfields):
    labels = []
    for df in dynfields:
        var_instance = df.variable_instance
        if df.multipart:
            label = var_instance.lablaxis[df.multipart_index - 1]
        else:
            label = var_instance.lablaxis
        labels.append(label)
    return labels

def _label_row_builder(variables, colwidths):
    cols = ["timestamp"]
    for var in variables:
        dyn_fields = var.dynamic.order_by('multipart_index') #TODO: steal the labels from plotting
        if dyn_fields.count() == 1:
            cols.append(var.name)
        else:
            for df in dyn_fields:
                cols.append(f"{var.name}_{df.multipart_index}")
    yield ",".join(cols) + "\n"
    #TODO: yield units

def _row_generator(query, ts_start, ts_end, format_map=None):

    #CHECKPOINT query execution and row generation

    if query.queryset.exists():
        query.set_record_arrays()

        # arrays[0] = timestamps, arrays[1:] = field values in same order as fields
        for i in range(query.get_record_count()):
            row = query.record_arrays[i]
            yield _row_formatter(row, format_map=format_map)
    else:
        #SQUIRREL: verification of empty or non-significant data - to the plan
        yield f"# No data for the specified time range {ts_start} to {ts_end}\n"


def _format_map_builder(dyn_fields):
    '''Build a list of formatter functions corresponding to the fields.'''

    format_map = []
    colwidths = []
    for df in dyn_fields:
        var_instance = df.variable_instance

        format_str = var_instance.format
        if df.multipart:
            label = var_instance.lablaxis[df.multipart_index - 1]
        else:
            label = var_instance.lablaxis

        #CHECKPOINT pasrse format_str and build formatter function
        #depends on datatype and actuall string??? i mean
        #epoch is none but shall output as timestamp
        #float is either fortran or scientific
        #everything else is fallback
        #ok it shal eat var instance

        formatter = make_formatter(var_instance)
        format_map.append(formatter)

        colwidth = max(len(label), len(format_str))+2 # +2 for padding
        colwidths.append(colwidth)

    return format_map, colwidths

def _row_formatter(row, format_map=None):
    '''format map application to a row, then conversion to CSV string.'''

    if format_map is None:
        format_map = [str] * len(row)
    formatted_row = []
    for item, f in zip(row, format_map):
        formatted_row.append(f(item))

    #CHECKPOINT use colwidths to add padding to the formatted items, for now just join with comma
    return ",".join(formatted_row) + "\n"

 # ====== FORMATTERS ======

# ===FORMATTERS===
#mmmmhhh closures i guess
def make_formatter(var):
    '''Factory for field-specific formatter functions.'''
    if var.format is None:
        return _format_fallback

    if dyn_field.field_name == "timestamp": #ugh it's not the correct firldname for that
        return _format_timestamp
    # elif dyn_field.field_name in int_fields:
    #     return _format_int
    # elif dyn_field.field_name in float_fortran_fields:
    #     return _format_float_fortran
    # elif dyn_field.field_name in float_scientific_fields:
    #     return _format_float_scientific
    else:
        return _format_fallback

def format_timestamp(value):
    '''Format bigint-like timestamp values using the project resolver.'''
    if value is None:
        return ""
    return str(it(value))

def format_int(value):
    pass

def format_float_fortran(value):
    pass

def format_float_scientific(value):
    pass

def format_fallback(value):
    '''Fallback formatter for numeric exports with safe empty handling.'''
    if value is None:
        return ""
    if np.isscalar(value) and np.isnan(value):
        return ""
    return str(value)

