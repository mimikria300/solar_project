from load_cdf.models import *
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import str_to_dt

import math
import datetime as dt
from pages.figures import scatter, n_trace


class DBQuery():


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
        self.arrays = None

        # bin mapping over over the array of epochs
        self.bin_map = None


    def query(self):
        kwargs = {
            '{0}__gte'.format(self.filter_field): self.start_limit,
            '{0}__lte'.format(self.filter_field): self.stop_limit,
        }
        self.queryset = self.data_class.objects.filter(**kwargs)
    
    # alternative way ?
    """
    def evaluate(self):sorted_pile = pile[pile[:, 0].argsort()]
        # no memory cache
        rows = self.queryset.values_list(*self.all_fields).iterator()
        # here is where slow evaluation happens
        arrays = [np.array(col) for col in zip(*rows)]
        self.named_arrays = dict(zip(fields, arrays))
    """

    def set_arrays(self):
        # if queryset is not completely empty
        if self.queryset.exists():
            rows = self.queryset.values_list(*self.all_fields)
            pile = np.stack(rows)
            print("PILE SHAPE", pile.shape)
            # sort everythong by the first row
            sorted_pile = pile[pile[:, 0].argsort()]
            # transpose to form arrays
            self.arrays = sorted_pile.T

    def get_array_len(self):
        if self.arrays is not None:
            return self.arrays[0].shape[0]

    def get_full_time_array(self):
        if self.arrays is not None:
            return self.arrays[0]

    def set_bin_map(self, bin_starts_array):
        self.bin_map = np.searchsorted(bin_starts_array, self.get_full_time_array(), side="right")


class Bin():

    # points per plot: since plot aggregation is dynamic, either need to have fixed bin sizes or points per plot
    PPP = 1000

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
            full_value_array = query.arrays[field_index]
            
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
            full_value_array = query.arrays[field_index]

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

