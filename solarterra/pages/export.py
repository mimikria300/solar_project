from load_cdf.models import DynamicField
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import NOW
import numpy as np
import datetime


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

def plain_text_generator(variables, ts_start, ts_end): #AKA single file generator. it actually may be packed into the class init
    '''
    Main streaming function to generate CSV data for the given variables and time range.
    Yields header block and rows per dataset.

    NB: works in streaming mode. 
    May later be changed for small data queres and left with a streaming version for bigger ones.
    '''

    dataset = variables[0].dataset
    
    # Yield header block for this dataset
    yield from _header_builder(variables, dataset)
    
    # Yield data table (labels + rows) for this dataset
    yield from _table_builder(variables, dataset, ts_start, ts_end)

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
    

def _table_builder(variables, dataset, ts_start, ts_end):

    depend_field = variables[0].get_depend_field()

    #CHECKPOINT query building

    # Get all field names ordered by variable name then component index to match header
    dyn_fields_q = DynamicField.objects.filter(variable_instance__in=variables).order_by('variable_instance__name', 'multipart_index')
    dyn_fields = list(dyn_fields_q.all())
    fields = [df.field_name for df in dyn_fields]
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
            cw = max(cw, len("YYYY-MM-DD HH-MM-SS-XXX"))
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

    #CHECKPOINT: query evaluation
    if query.queryset.exists():
        query.set_record_arrays()

        #CHECKPOINT building label row (colwidth applies)
        
        yield from _label_row_builder(labels, units, colwidths)
        yield from _row_generator(query, format_map, colwidths)
    
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

def _row_generator(query, format_map, colwidths):
    
    #CHECKPOINT row generation
    
    # arrays[0] = timestamps, arrays[1:] = field values in same order as fields
    for i in range(query.get_record_count()):
        row = query.record_arrays[i]
        yield _row_formatter(row, format_map, colwidths)
        

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

