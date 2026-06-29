#lib import
from load_cdf.models import *
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import bigint_ts_resolver as it
import math
import datetime as dt
import numpy as np

'''
NB: for convinience ts_start is always in timestamp format. 
The corresponding value in unix time shall be named as tu_start.
'''

class DataHandler():

    def __init__(self, dataset, filter_field, ts_start, ts_stop, fields):
        # instance
        self.dataset = dataset
        # class
        self.data_class = dataset.dynamic.resolve_class()

        # time bounds in timestamp form
        self.ts_start = ts_start
        self.ts_stop = ts_stop
        
        self.filter_field = filter_field
        self.data_fields = fields
        # field name on which the filtering happens
        self.filter_field_name = filter_field.field_name
        self.field_names_for_query = [df.field_name for df in self.data_fields] #field names, depend not included
        # 0th position of the filter_field is important
        self.all_field_names = [self.filter_field_name] + self.field_names_for_query

        # not evaluated queryset
        self.queryset = None
        # transposed and sorted arrays of values
        self.data_by_var = None
        # sorted arrays of records (timestamp + values)
        self.data_by_record = None

        # boolean mask, True for valid values, False for None/NaN, same shape as data arrays, set in set_mask() and updated in add_validation_to_mask()
        self.mask = None
        # bin mapping over the array of epochs
        self.bin_map = None
        self.bin_instance = None

    def query(self):

        #building lazy query
        kwargs = {
            "{0}__gte".format(self.filter_field): ti(self.ts_start),
            "{0}__lt".format(self.filter_field): ti(self.ts_stop),
        }
        self.queryset = self.data_class.objects.filter(**kwargs)

    def set_data(self):

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

            rows = self.queryset.values_list(*self.all_field_names)
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            # sort everything by the first row
            sorted_pile = pile[pile[:, 0].argsort()]

            # transpose to form arrays
            self.data_by_var = sorted_pile.T
            self.data_by_record = sorted_pile

            #apply the raw mask for None/NaN values to the data arrays
            self.set_mask()

    def set_mask(self):
        '''Set a boolean mask for values that is None/NaN'''
        if self.data_by_var is not None:
            self.mask = ~np.isnan(self.data_by_var)
        else:
            self.mask = None

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

    def add_validation_to_mask(self):
        '''Update the boolean mask in-place to mark out-of-bounds values as False.'''

        for idx, df in enumerate(self.data_fields, start=1):
            vmin_str, vmax_str = self._get_bounds_for_field(df)
            if vmin_str is None and vmax_str is None:
                continue
            
            arr_mask = self.mask[idx, :] #a view, will be edited in-place
            proper_arr = self.data_by_var[idx, :].copy().astype(df.data_type_instance.numpy_type)
            #get first non-NaN value as sample for proper_type parsing of the bound
            sample = proper_arr[arr_mask][0] if arr_mask.any() else None
            if vmin_str is not None:
                bound = DataType.proper_type(vmin_str, sample)
                if bound is not None:
                    arr_mask &= proper_arr >= bound
            if vmax_str is not None:
                bound = DataType.proper_type(vmax_str, sample)
                if bound is not None:
                    arr_mask &= proper_arr <= bound

    def clean_data(self):
        '''Cast data into proper types, swap unvalid values to None, then converts to numpy object'''
        for idx, df in enumerate(self.data_fields, start=1):
            var_array = self.data_by_var[idx, :]
            mask = self.mask[idx, :]
            ok_values = var_array[mask].astype(df.data_type_instance.numpy_type)
            clean_var_array = np.full(var_array.shape, None, dtype=object)
            clean_var_array[mask] = ok_values
            self.data_by_var[idx, :] = clean_var_array

        # Keep row-wise view aligned with cleaned column-wise arrays 
        # (otherwise it will catch object type as numeric and mess with nan)
        self.data_by_record = self.data_by_var.T
            

    #---AGGREGATION---
    def set_bin_arrays(self):

        ts_start = self.ts_start
        ts_stop = self.ts_stop
        self.bin_instance = Bin(ts_start, ts_stop)

        # Bin edges for [start, stop] with one extra edge for right-open intervals.
        bin_edges_array = np.arange(
            ti(ts_start),
            ti(ts_stop) + (self.bin_instance.bin_seconds),
            step=self.bin_instance.bin_seconds,
        )
        #getting rid of bins that doesn't have any epoch in them, to avoid having a lot of empty bins in case of sparse data
        epoch_array = self.get_full_time_array()
        is_there_epoch_in_bin = np.zeros(bin_edges_array.shape[0], dtype=bool)
        is_there_epoch_in_bin[np.unique(np.searchsorted(bin_edges_array, epoch_array, side="right") - 1)] = True
        
        bin_edges_array = bin_edges_array[is_there_epoch_in_bin]
        bin_centers_array = bin_edges_array + (self.bin_instance.half_bin)

        self.bin_edges_array = bin_edges_array
        self.bin_centers_array = bin_centers_array

    def set_bin_map(self):
        # Return 0-based bin indices for half-open bins [edge_i, edge_{i+1}).
        # -1 because right-sided searchsorted returns the index of the place to insert the value to keep order, which is after the bin idx
        self.bin_map = np.searchsorted(self.bin_edges_array, self.get_full_time_array(), side="right") - 1

    def set_aggregated_data(self):
        '''Set an aggregated version of the data_by_record and data_by_var based on the bin_map and bin centers.
        The bin centers are calculated in the export function.
        Aggregated data is cast into object numpy type. Also cleans data as clean_data does, but not in-place'''
        
        # initialize empty arrays for aggregated data
        agg_data_by_var = [self.bin_centers_array]
        for idx, df in enumerate(self.data_fields, start=1):

            var_array = self.data_by_var[idx, :]
            mask = self.mask[idx, :]

            #filtering out unvalid values and their bin indexies
            ok_bins = self.bin_map[mask]
            ok_values = var_array[mask].astype(df.data_type_instance.numpy_type)

            #group bins
            bin_id, pos, count = np.unique(ok_bins, return_index=True, return_counts=True)
            #count means for each bin
            means = np.add.reduceat(ok_values, pos, axis=0) / count
            #restore missing empty bins, filling with None to pass to formatter, now in object type after all math handling
            agg_var_array = np.full(self.bin_centers_array.shape[0], None, dtype=object)
            agg_var_array[bin_id] = means
            agg_data_by_var.append(agg_var_array)

        agg_data_by_var = np.stack(agg_data_by_var, axis=0)

        #crudely throwing away the last bin, not to confuse user of why it sticks out
        if self.bin_centers_array[-1] > ti(self.ts_stop):
            agg_data_by_var = agg_data_by_var[:, :-1]

        self.agg_data_by_var = agg_data_by_var
        self.agg_data_by_record = self.agg_data_by_var.T


    #---HELPERS---
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
        else:
            return None

    def test(self):
        print("DATA BY VAR", self.data_by_var)
        print("DATA BY RECORD", self.data_by_record)
        #numpy datatypes vs proper DataType numpy types for every field
        ff = self.filter_field
        print(f"FILTER FIELD: {ff.field_name}, ACTURAL TYPE: {self.data_by_var[0].dtype}, NUMPY PROPER TYPE: {ff.data_type_instance.numpy_type}")
        for n,df in enumerate(self.data_fields, start=1):
            print(f"FIELD: {df.field_name}, ACTURAL TYPE: {self.data_by_var[n].dtype}, NUMPY PROPER TYPE: {df.data_type_instance.numpy_type}")

class Bin():

    # points per plot: since plot aggregation is dynamic, either need to have fixed bin sizes or points per plot
    #TODO: rename, make default option which calculates dynamically 
    PPP = 1000
    #TODO: add wiring for setting PPP manually

    def __init__(self, ts_start, ts_stop):

        timedelta = ts_stop - ts_start 
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

    def __init__(self, var_group):

        #var_group should belong to a single dataset and have the same depend_0
        self.var_group = var_group
        self.dataset = var_group[0].dataset

        self.labels = None
        self.units = None
        self.type_and_format_pairs = None
        self.format_map = None

        self.depend_field = var_group[0].get_depend_field()

        # Get all field names ordered by variable name then component index to match header
        dyn_fields_q = DynamicField.objects.filter(variable_instance__in=var_group).order_by('variable_instance__name', 'multipart_index')
        self.dyn_fields = list(dyn_fields_q.all()) #field instances
        print(
            f"[EXPORT] in _table_builder. dataset={self.dataset.tag}, depend_field={self.depend_field.field_name}, "
            f"dynamic_fields={self.dyn_fields}"
        )
        # prepend epoch/depend field so labels, units, formats, colwidths align with record_arrays column order
        # epoch isn't added to fields which are passed to query because it will be added as the filter_field in the query
        self.dyn_fields = [self.depend_field] + self.dyn_fields

        self.info = {
            'validate': False,
            'unvalid_count': [],
            'aggregate': False,
            'bin_size': None,
            'survived_bins': None,
            'ts_start': None, 
            'ts_stop': None,
            'status': {},
            'notes': '',
        }

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
            format_str = df.get_format_str()
            type_instance = df.data_type_instance
            self.type_and_format_pairs.append((type_instance, format_str))

    def set_format_map(self):

        '''
        Build a list of formatter functions corresponding to the fields.
        Sorted by the order of fields in the record arrays, which is the same as the order of field names in field_names_for_query.
        '''

        self.format_map = []
        for type_instance, format_str in self.type_and_format_pairs:

            formatter = DynamicField.make_format_function(type_instance, format_str)
            self.format_map.append(formatter)

        #alternatively, if we are sure format functions are set
        # for df in self.dyn_fields:
        #     formatter = df.format_function
        #     self.format_map.append(formatter)

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
    
    def _format_row(self, row):
        '''Format map application to a row, then conversion to fixed-width string.'''
        formatted_row = [" "]  # to correct first column padding to the # symbol in labels
        for value, formatter, cw in zip(row, self.format_map, self.colwidths):
            formatted_value = formatter(value)
            formatted_value = ' '*(cw - len(formatted_value)) + formatted_value
            formatted_row.append(formatted_value)
        return "".join(formatted_row) + "\n"

    def stream_formatted_rows(self, rows):

        '''Yield formatted data rows.'''
        for row in rows:
            yield self._format_row(row)

    def stream_footer(self):
        from solarterra.utils import NOW
        yield f"# End of data in the chosen interval for the dataset: {self.dataset.tag}.\n# File generated at {NOW()}\n"
        if self.info['validate']:
            yield f'# Data is validated to be in min\max bounds.\n'
            #TODO: add counter for nulled data for each var
            # yield f"Nulled {self.info['validation_removed_count']}" or some for-loop over every var or add tuple to "unvalid_counters", yes that
        else:
            yield '# Data is not validated to be in bounds.\n'
        #TODO: once we'll got the resolution match-field, we can add max points per bin to the metainfo.
        if self.info['aggregate']:
            yield f"# Data is aggregated by averaging. Bin size (time delta): {self.info['bin_size']}s. Note that empty bins may be produced by gaps in data.\n"
            yield f"# Requested data interval: {self.info['ts_start']} to {self.info['ts_end']}.\n"
            yield "# Time entries represent the aggregation bins' middle points.\n"
            #TODO: add survived bins counter
            #Number of non-empty bins: {self.info['survived_bins']}/1000.
        else:
            yield "# No aggregation performed.\n"
        
        yield self.info['notes']
