# Data gathering and processing shared across export formats

from load_cdf.models import *
from solarterra.utils import ts_float_resolver as tf
from solarterra.utils import float_ts_resolver as ft
import math
import datetime as dt
import numpy as np

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
            "{0}__gte".format(self.filter_field): tf(self.ts_start),
            "{0}__lt".format(self.filter_field): tf(self.ts_stop),
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

            rows = list(self.queryset.values_list(*self.all_field_names))

            # expand array field columns into N scalar columns before stacking
            if any(df.is_array_field for df in self.data_fields):
                expanded = []
                for row in rows:
                    flat = [row[0]]  # epoch
                    for i, df in enumerate(self.data_fields):
                        val = row[i + 1]
                        if df.is_array_field:
                            if val is not None:
                                flat.extend(val)
                            else:
                                # Use np.nan for numeric types, None for string/object types
                                missing_val = np.nan if df.data_type_instance and df.data_type_instance.is_numeric() else None
                                flat.extend([missing_val] * df.array_size)
                        else:
                            flat.append(val)
                    expanded.append(flat)
                rows = expanded

            print("[EXPORT] Data sample (first row):", rows[0] if rows else "No data")
            print("[EXPORT] Data types in first row:", [type(v).__name__ for v in rows[0]] if rows else "No data")
            
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            print("[EXPORT] PILE DTYPE:", pile.dtype)
            # sort everything by the first row
            sorted_pile = pile[pile[:, 0].argsort()]

            # transpose to form arrays
            self.data_by_var = sorted_pile.T
            self.data_by_record = sorted_pile

            #apply the raw mask for None/NaN values to the data arrays
            self.set_mask()

    def set_mask(self):
        '''Set a default boolean mask for values that is None/NaN, can be expanded with validation checks'''
        if self.data_by_var is not None:
            # Handle both numeric and non-numeric dtypes
            try:
                self.mask = ~np.isnan(self.data_by_var)
            except TypeError as e:
                # For non-numeric dtypes (strings, objects), check for None explicitly
                print(f"[EXPORT] set_mask() encountered non-numeric data. Array dtype: {self.data_by_var.dtype}, shape: {self.data_by_var.shape}")
                print(f"[EXPORT] Field names involved: {self.all_field_names}")
                print(f"[EXPORT] Error: {e}")
                self.mask = self.data_by_var != None
        else:
            self.mask = None

    #---VALIDATION---
    def _get_bounds_for_field(self, dyn_field, index=None):
        '''Resolve validmin/validmax for a dynamic field, using index for array field components.'''
        variable = dyn_field.variable_instance

        vmin = variable.validmin
        if vmin is not None and dyn_field.is_array_field and index is not None and isinstance(vmin, list):
            vmin = vmin[index]

        vmax = variable.validmax
        if vmax is not None and dyn_field.is_array_field and index is not None and isinstance(vmax, list):
            vmax = vmax[index]

        return vmin, vmax

    def add_validation_to_mask(self):
        '''Update the boolean mask in-place to mark out-of-bounds values as False.'''

        expanded = [(df, i) for df in self.data_fields for i in (range(df.array_size) if df.is_array_field else [None])]
        for idx, (df, index) in enumerate(expanded, start=1):
            vmin_str, vmax_str = self._get_bounds_for_field(df, index)
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
        expanded = [df for df in self.data_fields for _ in (range(df.array_size) if df.is_array_field else [None])]
        for idx, df in enumerate(expanded, start=1):
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
            tf(ts_start),
            tf(ts_stop) + (self.bin_instance.bin_seconds),
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

        # expand array fields so column indices match data_by_var
        expanded_fields = []
        for df in self.data_fields:
            if df.is_array_field:
                expanded_fields.extend([df] * df.array_size)
            else:
                expanded_fields.append(df)

        for idx, df in enumerate(expanded_fields, start=1):

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
        if self.bin_centers_array[-1] > tf(self.ts_stop):
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
        #self.bin_seconds = math.ceil(timedelta.total_seconds() / self.PPP)
        self.bin_seconds = timedelta.total_seconds() / self.PPP
        self.bin_td = dt.timedelta(seconds=self.bin_seconds)
        #self.half_bin = math.ceil(self.bin_seconds / 2)
        self.half_bin = self.bin_seconds / 2

    def t_next(self, t_current):
        #print(f"in t_next : {t_current}, {t_current + self.bin_td}")
        return t_current + self.bin_td

    def t_previous(self, t_current):
        #print(f"in t_prev : {t_current}, {t_current - self.bin_td}")
        return t_current - self.bin_td
