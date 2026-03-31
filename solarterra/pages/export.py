from load_cdf.models import DynamicField
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import NOW
import numpy as np
import datetime

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

def csv_generator(variables, ts_start, ts_end): #AKA single file generator. it actually may be packed into the class init
    '''
    Main streaming function to generate CSV data for the given variables and time range.
    Yields header block and rows per dataset.

    NB: works in streaming mode. 
    May later be changed for small data queres and left with a streaming version for bigger ones.
    '''

    dataset = variables[0].dataset
    depend_field = variables[0].get_depend_field()
    
    # Yield header block for this dataset
    #FIXME shall be not yielded, i want a plain return
    # the generator MIGHT yield it row but row but the header-gen must give out the whole header at a time
    yield from _header_builder(variables, dataset)
    
    # Yield data table (labels + rows) for this dataset
    yield from _table_builder(variables, dataset, depend_fiels, ts_start, ts_end)
    
    yield f"# End of data in the chosen interval for the dataset: {dataset.tag}\nFile generated at {NOW()}"

def _header_builder(variables, dataset):
    '''Header block for one file.'''
     
    # not a tuple, python convention for readability
    ga = (
        '#              ************************************\n'
        '#              *****    GLOBAL ATTRIBUTES    ******\n'
        '#              ************************************\n'
        '#\n'
    )

    match_attributes = dataset.attributes.filter(linked_standard_field__isnull=False)
    mf_str = ''
    #render matches like # standard_name: attribute_name = attribute_value
    #i am not sure mf label matches with fieldname in the model
    #maybe render all fields from dataset... egh
    for attr in match_attributes:
        #not pretty, yet will do fn
        mf_str += f"#     {attr.linked_standard_field.name.upper()}: {attr.name} = {attr.value}\n"
    mf_str += '#\n'

    rvv = (
        '#              ************************************\n'
        '#              ****  RECORD VARYING VARIABLES  ****\n'
        '#              ************************************\n'
        '#\n'
    )
    
    var_desc = ''
    for i, var in enumerate(variables,1):
        catdesc = var.catdesc
        var_desc += f'#   {i}. {catdesc}\n'

    var_desc += '#\n'

    yield ga + mf_str + rvv + var_desc
    

def _table_builder(variables, dataset, depend_field, ts_start, ts_end):

    #CHECKPOINT query building

    # Get all field names ordered by variable name then component index to match header
    dyn_fields_q = DynamicField.objects.filter(variable_instance__in=variables).order_by('variable_instance__name', 'multipart_index')
    dyn_fields = list(dyn_fields_q.all())
    fields = [df.field_name for df in dyn_fields]
    
    query = DBQuery(
        dataset=dataset,
        filter_field=depend_field,
        t_start=ts_start,
        t_stop=ts_end,
        fields=fields
    )
    
    query.query()

    #CHECKPOINT getting labels and units

    labels = []
    units = []
    for df in dyn_fields:
        var_instance = df.variable_instance
        if df.multipart:
            label = var_instance.lablaxis[df.multipart_index - 1]
            unit = var_instance.unit[df.multipart_index - 1]
        else:
            label = var_instance.lablaxis
            var_instance.unit
        labels.append(label)
        units.append(unit)

    
    #CHECKPOINT getting formats and DataType instances

    type_and_format_pairs = []
    for df in dyn_fields:
        var_instance = df.variable_instance
        if df.multipart:
            format_str = var_instance.format[df.multipart_index - 1]
        else:
            format_str = var_instance.format
        type_instance = var_instance.data_type
        type_and_format.append((type_instance, format_str))

    #CHECKPOINT building format map
    format_map = _format_map_builder(type_and_format_pairs)

    #CHECKPOINT building colwidths
    colwidths = []
    for label, tf_pair, unit in zip(labels, type_and_format_pairs, units):
        cw = max(len(label), len(unit))
        type_instance, format_str = tf_pair
        if type_instance.is_epoch():
            cw = max(cw, len("YYYY-MM-DD HH:MM:SS"))
        elif format_str is not None and "i" in format_str.lower():
            cw = max(cw, int(format_str.lower().strip("i")))
        elif format_str is not None and "f" in format_str.lower():
            # this is a bit of a hack, but it gives us a minimum width for floats based on the format string
            cw = max(cw, int(format_str.lower().strip("f").split(".")[0]))
        elif format_str is not None and "e" in format_str.lower():
            # scientific notation can be quite long, so we give it a generous width based on the format string
            cw = max(cw, int(format_str.lower().strip("e").split(".")[0]) + 5)
        else:
            #would be nice to evaluate the length of the string based on the actual data
            cw = max(cw, 10)
        colwidths.append(cw+2) #+2 for padding

    #CHECKPOINT: query evaluation
    if query.queryset.exists():
        query.set_record_arrays()

        #CHECKPOINT building label row (colwidth applies)
        
        yield from _label_row_builder(labels, units, colwidths)
        yield from _row_generator(query, ts_start, ts_end, format_map=format_map)
    
    else:

        #SQUIRREL: verification of empty or non-significant data - to the plan; it shall use the exact approach as plotting, but here i print it into the file
        yield f"# No data for the specified time range {ts_start} to {ts_end}\n"


    

def _label_row_builder(labels, units, colwidths):
    lblrow = []
    unitrow = []
    for label, unit, cw in zip(labels, units, colwidths):
        lblrow.append(' '*(cw - len(label)) + label)
        unitrow.append(' '*(cw - len(unit)) + unit)
   
    yield "".join(lblrow) + "\n"
    yield "".join(unitrow) + "\n"

def _row_generator(query, ts_start, ts_end, format_map=None):
    
    #CHECKPOINT row generation
    
    # arrays[0] = timestamps, arrays[1:] = field values in same order as fields
    for i in range(query.get_record_count()):
        row = query.record_arrays[i]
        yield _row_formatter(row, format_map=format_map)
        

def _row_formatter(row, format_map, colwidths):
    '''format map application to a row, then conversion to CSV string.'''

    formatted_row = []
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
        return lambda x: it(x).strftime("%Y-%m-%d %H:%M:%S") if x is not None else ""
    elif format_str is not None and "i" in format_str.lower():
        #i is usually for year/day/etc, doesn't really need to be zero-padded; added as a place to add different bechavior for int types if needed
        return lambda x: str(x) if x is not None else ""
    elif format_str is not None and "f" in format_str.lower():
        return lambda x: f"{x:.{format_str.lower().strip('f')}f}" if x is not None else ""
    elif format_str is not None and "e" in format_str.lower():
        #scientific float formatter
        return lambda x: f"{x:.{format_str.lower().strip('e')}e}" if x is not None else ""
    else:
        #fallback
        return lambda x: str(x) if x is not None else ""

