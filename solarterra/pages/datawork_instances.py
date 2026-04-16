from load_cdf.models import *
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import str_to_dt

import math
import datetime as dt
from pages.figures import scatter, n_trace
import numpy as np


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
    
    def get_record_count(self):
        if self.record_arrays is not None:
            return self.record_arrays.shape[0]

    def get_full_time_array(self):
        if self.var_arrays is not None:
            return self.var_arrays[0]
        elif self.record_arrays is not None:
            return self.record_arrays[:, 0]

    def set_bin_map(self, bin_starts_array):
        self.bin_map = np.searchsorted(bin_starts_array, self.get_full_time_array(), side="right")

class Bin():

    # points per plot: since plot aggregation is dynamic, either need to have fixed bin sizes or points per plot
    PPP = 1000

    #TODO for export, add custom bin sizes for user to pass
    def __init__(self, t_start, t_stop):

        timedelta = t_stop - t_start 
        self.bin_seconds = math.ceil(timedelta.total_seconds() / self.PPP)
        self.bin_td = dt.timedelta(seconds=self.bin_seconds)
        self.half_bin = math.ceil(self.bin_seconds / 2)

    def t_next(self, t_current):
        #print(f"in t_next : {t_current}, {t_current + self.bin_td}")
        return t_current + self.bin_td

    def t_previous(self, t_current):
        #print(f"in t_prev : {t_current}, {t_current - self.bin_td}")
        return t_current - self.bin_td

class Plot():

    # start and stop as datetimes
    t_start = None
    t_stop = None
    
    # in seconds
    bin_instance = None
    # numpy range of the starts of time bins
    bin_starts_array = None
    bin_centers_array = None

    # plotly figure
    figure = None

    def __init__(self, t_start, t_stop, variable, x_field, validate):

        # start and stop as datetimes
        self.t_start = t_start
        self.t_stop = t_stop

        # instances of var
        self.variable = variable
      
        # Flag to show if validation will be applied
        self.validate = validate

        # Flag to now if aggregation happened
        self.aggregation = None

        # block for aggregation
        self.bin_instance = None
        # numpy range of the starts of time bins
        self.bin_starts_array = None
        self.bin_centers_array = None

        # name of x_field
        self.x_field = x_field
        # array of timestamps for plot points
        self.x_field_array = None

        # numpy datatype
        self.y_field_numpy_type = variable.get_numpy_data_type()
        # names of y_fields
        self.y_fields = list(variable.dynamic.order_by('multipart_index').values_list('field_name', flat=True))
        # a list of field arrays, in the same order as y_fields
        self.y_arrays = []
        
        self.invalid_values = []
        
        self.figure = None



    def prepare_bins(self, bin_instance):
        i_start = ti(self.t_start)
        i_stop = ti(self.t_stop)
        self.bin_instance = bin_instance
        # *2 here because right limit in arange is non-inclusive, 
        # but a little data in the query could be left beyond last bin, since bin size is rounded
        self.bin_starts_array = np.arange(
                i_start,
                i_stop + (bin_instance.bin_seconds*2),
                step=bin_instance.bin_seconds)
        self.bin_centers_array = self.bin_starts_array + bin_instance.half_bin
    
    # index that marks values beyond validmin - valimax interval
    def validation_index(self, arr, field_index=None):
        condition = False
        
        if self.variable.validmin is not None:
            #print(type(self.variable.validmin))
          
            if field_index is not None and isinstance(self.variable.validmin, list):
                validmin = self.variable.validmin[field_index]
            else:
                validmin = self.variable.validmin
            validmin_value = DataType.proper_type(validmin, arr[0])
           
            condition = condition | (arr < validmin_value)

        if self.variable.validmax is not None:
            if field_index is not None and isinstance(self.variable.validmax, list):
                validmax = self.variable.validmax[field_index]
            else:
                validmax = self.variable.validmax
            validmax_value = DataType.proper_type(validmax, arr[0])
           
            condition = condition | (arr > validmax_value)
    
        # can not just swap values here, because for int type there is no nan alternative

        if isinstance(condition, np.ndarray):
            self.invalid_values.append(f"{int(condition.sum())} / {condition.shape[0]} [{validmin}, {validmax}]")
        else:
            condition = None
            self.invalid_values.append("no validmin/validmax")
        
        if self.validate:
            return condition
        else:
            return None


    def get_x_array(self, query):
        self.x_field_array = np.array(list(map(it, query.get_full_time_array())))

    def get_y_arrays(self, query):
        for field in self.y_fields:
            field_index = query.all_fields.index(field)
            full_value_array = query.var_arrays[field_index]
            
            # only nan values for this variable
            if np.isnan(full_value_array).all():
                self.y_arrays.append([])
            else:
                self.y_arrays.append(full_value_array.astype(self.y_field_numpy_type))

        # applying validation index in case of no aggregation is a little harder:
        # the only way to skip values when plotting is skipping index in both x_array and y_array at the same index
        # but there is a single x array and y arrays could have different validation indexes so i have to have multiple x_arrays or apply aggregation when plotting
        # chose the second option

    def get_agg_x_array(self):
        self.x_field_array = np.array(list(map(it, self.bin_centers_array)))

    # definitely could reduce # of steps here
    def get_agg_y_arrays(self, query):
        
        for i, field in enumerate(self.y_fields):
            field_index = query.all_fields.index(field)
            full_value_array = query.var_arrays[field_index]

            # getting an index of nans in value array
            mask = ~np.isnan(full_value_array)
           
            # getting an index of invalid values
            validation_index = self.validation_index(full_value_array, field_index=i)
            # if index exists and there is at least one invalid value, combine it with the mask
            if validation_index is not None and validation_index.any():
                mask = mask & ~validation_index

            
            # getting maps for only non-nans
            val_bin_map = query.bin_map[mask]
            # getting only non-nans
            val_array = full_value_array[mask]

            idx, pos, counts = np.unique(val_bin_map, return_index=True, return_counts=True)

            # number of groups even left
            # if no aggregation groups survived - that means there will be no points on the plot
            if idx.shape[0] == 0:
                print(f"no data in field {field}, out of {self.variable.name} {self.variable.dataset}")
                self.y_arrays.append([])
                continue

            # getting sums for groups
            sums = np.add.reduceat(val_array, pos, axis=0)
            # getting values
            means = sums / counts
            # reconstructing index
            np_type = self.y_field_numpy_type if self.y_field_numpy_type is not None else means.dtype
            # get an array of nans of size and type
            result = np.full(self.x_field_array.shape, np.nan, np_type)
            # fill in significant values
            result[idx] = means
            self.y_arrays.append(result)
        
    def set_arrays(self, query):
        # includes validation
        if self.aggregation:
            self.get_agg_x_array()
            self.get_agg_y_arrays(query)

        # validation on plotting, because no nans for int types means no swap
        else:
            self.get_x_array(query)
            self.get_y_arrays(query)

    # returns a pair of x_array and y_array for each plot
    def get_values(self, index):
        if self.aggregation:
            return self.x_field_array, self.y_arrays[index]
        else:
            # apply validation here instead:
            validation_index = self.validation_index(self.y_arrays[index], field_index=index)
            if validation_index is not None and validation_index.any():
                return self.x_field_array[~validation_index], self.y_arrays[index][~validation_index]
            else:
                return self.x_field_array, self.y_arrays[index]
    


    def get_figure(self):
    
        if len(self.y_fields) == 1:
            self.figure = scatter(self)
        else:
            self.figure = n_trace(self)

class PlainTextFile():

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

    def __init__(self, var_group, dataset):

        #var_group should belong to a single dataset and have the same depend_0
        self.var_group = var_group
        self.dataset = dataset

        self.labels = None
        self.units = None
        self.type_and_format_pairs = None
        self.format_map = None

        self.depend_field = var_group[0].get_depend_field()

        # Get all field names ordered by variable name then component index to match header
        dyn_fields_q = DynamicField.objects.filter(variable_instance__in=var_group).order_by('variable_instance__name', 'multipart_index')
        self.dyn_fields = list(dyn_fields_q.all()) #field instances
        self.field_names_for_query = [df.field_name for df in self.dyn_fields] #field names, depend not included
        print(
            f"[EXPORT] in _table_builder. dataset={dataset.tag}, depend_field={self.depend_field.field_name}, "
            f"dynamic_fields={self.dyn_fields}"
        )
        # prepend epoch/depend field so labels, units, formats, colwidths align with record_arrays column order
        # epoch isn't added to fields which are passed to query because it will be added as the filter_field in the query
        self.dyn_fields = [self.depend_field] + self.dyn_fields
        
    def set_labels_and_units(self):

        self.labels = ['Epoch']
        self.units = ['dd-mm-yyyy hh:mm:ss.ms']
        for df in self.dyn_fields[1:]:
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
            self.labels.append(label if label is not None else '')
            self.units.append(unit if unit is not None else '')
        
    def set_type_and_format_pairs(self):

        self.type_and_format_pairs = []
        for df in self.dyn_fields:
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
            self.type_and_format_pairs.append((type_instance, format_str))

    def set_format_map(self):
    
        '''
        Build a list of formatter functions corresponding to the fields.
        Sorted by the order of fields in the record arrays, which is the same as the order of field names in field_names_for_query.
        '''

        #lazy to avoid circular import; later will be moved to dynamicfield class and called from there
        from pages.export import make_format_function
        self.format_map = []
        for type_instance, format_str in self.type_and_format_pairs:

            formatter = make_format_function(type_instance, format_str)
            self.format_map.append(formatter)

    def set_colwidths(self):
        self.colwidths = []
        for label, tf_pair, unit in zip(self.labels, self.type_and_format_pairs, self.units):
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
            self.colwidths.append(cw+5) #+5 for padding

    def generate_header(self):
        '''Yield the file header block: global attributes + record varying variable descriptions.'''

        depend_var = self.var_group[0].get_depend_var()
        described_variables = list(self.var_group)
        if depend_var is not None and all(var.id != depend_var.id for var in described_variables):
            described_variables = [depend_var] + described_variables

        #not a tuple, python convention for formatting
        ga = (
            '#              ************************************\n'
            '#              *****    GLOBAL ATTRIBUTES    ******\n'
            '#              ************************************\n'
            '#\n'
        )

        mf_str = self._render_global_attributes()

        rvv = (
            '#              ************************************\n'
            '#              ****  RECORD VARYING VARIABLES  ****\n'
            '#              ************************************\n'
            '#\n'
        )

        var_desc = ''
        for i, var in enumerate(described_variables, 1):
            catdesc = var.catdesc
            var_desc += f'#   {i}. {catdesc}\n'
        var_desc += '#\n'

        yield ga + mf_str + rvv + var_desc

    def _render_global_attributes(self):
        title_map = {}
        for attr in self.dataset.attributes.filter(linked_standard_field__isnull=False):
            standard_key = attr.linked_standard_field.upper()
            if standard_key not in title_map:
                title_map[standard_key] = attr.title

        lines = []
        for standard_key, dataset_field in self.GLOBAL_ATTRIBUTE_MAP:
            value = getattr(self.dataset, dataset_field, None)
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

    def generate_label_rows(self):
        '''Yield the column label row and unit row.'''
        lblrow = ['#']
        unitrow = ['#']
        for label, unit, cw in zip(self.labels, self.units, self.colwidths):
            lblrow.append(' '*(cw - len(label)) + label)
            unitrow.append(' '*(cw - len(unit)) + unit)

        yield "".join(lblrow) + "\n"
        yield "".join(unitrow) + "\n"

    def generate_rows(self, rows):
        '''Yield formatted data rows.'''
        for row in rows:
            yield self._format_row(row)

    def _format_row(self, row):
        '''Format map application to a row, then conversion to fixed-width string.'''
        formatted_row = [" "]  # to correct first column padding to the # symbol in labels
        for value, formatter, cw in zip(row, self.format_map, self.colwidths):
            formatted_value = formatter(value)
            formatted_value = ' '*(cw - len(formatted_value)) + formatted_value
            formatted_row.append(formatted_value)
        return "".join(formatted_row) + "\n"

    #maybe could be used to log smth
    def generate_footer(self):
        from solarterra.utils import NOW
        yield f"# End of data in the chosen interval for the dataset: {self.dataset.tag}\nFile generated at {NOW()}"
