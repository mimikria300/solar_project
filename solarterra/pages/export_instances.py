#lib import
from load_cdf.models import *
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import bigint_ts_resolver as it
import math
import datetime as dt
import numpy as np

#CHECKPOINT: dbquery

class DataHandler():

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
        self.data_by_var = None
        # sorted arrays of records (timestamp + values)
        self.data_by_record = None

        # bin mapping over over the array of epochs
        self.bin_map = None

    def query(self):

        #building lazy query
        kwargs = {
            "{0}__gte".format(self.filter_field): self.start_limit,
            "{0}__lte".format(self.filter_field): self.stop_limit,
        }
        self.queryset = self.data_class.objects.filter(**kwargs)

    def get_data(self):

        '''
        Executes queryset, sets numpy views for array in following format:

        1. data_by_var:
        arrays[0] = timestamps, arrays[1:] = field values in same order as fields
        epoch array
        field value array 1
        field value array 2

        2. data_by_record:
        rows[0] = [timestamp, value1, value2, ...]
        rows[1] = [timestamp, value1, value2, ...]
        '''

        # if queryset is not completely empty
        if self.queryset.exists():

            rows = self.queryset.values_list(*self.all_fields)
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            # sort everythong by the first row
            sorted_pile = pile[pile[:, 0].argsort()]

            # transpose to form arrays
            self.data_by_var = sorted_pile.T
            self.data_by_record = sorted_pile

    def get_var_array_len(self):
        if self.data_by_var is not None:
            return self.data_by_var[0].shape[0]

    def get_record_count(self):
        if self.data_by_record is not None:
            return self.data_by_record.shape[0]

    def get_full_time_array(self):
        if self.data_by_var is not None:
            return self.data_by_var[0]
        elif self.data_by_record is not None:
            return self.data_by_record[:, 0]

    #---VALIDATION---
    def _get_bounds_for_field(self, dyn_field):
        '''Resolve validmin/validmax for a dynamic field, accounting for multipart variables.'''
        variable = dyn_field.variable_instance

        vmin = variable.validmin
        if vmin is not None and dyn_field.multipart and isinstance(vmin, list):
            vmin = vmin[dyn_field.multipart_index - 1]

        vmax = variable.validmax
        if vmax is not None and dyn_field.multipart and isinstance(vmax, list):
            vmax = vmax[dyn_field.multipart_index - 1]

        return vmin, vmax

    def validate_array(self, arr, dyn_field):
        '''Return a float copy of arr with out-of-bounds values set to NaN.'''
        var = dyn_field.variable_instance
        vmin_raw, vmax_raw = self._get_bounds_for_field(dyn_field)
        result = np.array(arr, dtype=float)

        if vmin_raw is None and vmax_raw is None:
            return result

        non_nan = ~np.isnan(result)
        if not non_nan.any():
            return result

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

    def apply_validation_to_records(self, rows, data_dyn_fields):
        '''Validate the non-aggregated record_arrays in-place.
        Sets out-of-bounds cells to None so the row formatter renders them as blank.
        Iterates over data columns (skipping col 0 = epoch).'''
        for col_idx, df in enumerate(data_dyn_fields, start=1):
            var = df.variable_instance
            vmin_raw, vmax_raw = self._get_bounds_for_field(df)
            if vmin_raw is None and vmax_raw is None:
                continue

            col = rows[:, col_idx]
            # cast column to float for numeric comparison
            #HUH r we sure, i don't understand the mechanic here
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

    #---AGGREGATION HELPERS---
    def set_bin_map(self, bin_edges_array):
        # Return 0-based bin indices for half-open bins [edge_i, edge_{i+1}).
        self.bin_map = np.searchsorted(bin_edges_array, self.get_full_time_array(), side="right") - 1


class Bin():

    # points per plot: since plot aggregation is dynamic, either need to have fixed bin sizes or points per plot
    #TODO: rename, make default option which calculates dynamically 
    PPP = 1000
    #TODO: add wiring for setting PPP manually

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


class PlainTextMeta():


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
        #TODO: move type_and_format to dynfield model; let it have a formatting function in it
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

    def set_everything(self):
        self.set_labels_and_units()
        self.set_type_and_format_pairs()
        self.set_format_map()
        self.set_colwidths()

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

    #----STREAMING FUNCTIONS----

    def stream_header(self):
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

    def stream_label_rows(self):
        '''Yield the column label row and unit row.'''
        lblrow = ['#']
        unitrow = ['#']
        for label, unit, cw in zip(self.labels, self.units, self.colwidths):
            lblrow.append(' '*(cw - len(label)) + label)
            unitrow.append(' '*(cw - len(unit)) + unit)

        yield "".join(lblrow) + "\n"
        yield "".join(unitrow) + "\n"

    def stream_formatted_rows(self, rows):

        def _format_row(self, row):
            '''Format map application to a row, then conversion to fixed-width string.'''
            formatted_row = [" "]  # to correct first column padding to the # symbol in labels
            for value, formatter, cw in zip(row, self.format_map, self.colwidths):
                formatted_value = formatter(value)
                formatted_value = ' '*(cw - len(formatted_value)) + formatted_value
                formatted_row.append(formatted_value)
            return "".join(formatted_row) + "\n"

        '''Yield formatted data rows.'''
        for row in rows:
            yield self._format_row(row)

    
    #maybe could be used to log smth
    def stream_footer(self):
        from solarterra.utils import NOW
        yield f"# End of data in the chosen interval for the dataset: {self.dataset.tag}\nFile generated at {NOW()}"


# Backward-compatibility aliases while refactor settles.
DataHaldler = DataHandler
DBQuery = DataHandler
PlainTextFile = PlainTextMeta

