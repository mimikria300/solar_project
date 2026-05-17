from load_cdf.models import *
from solarterra.utils import ts_bigint_resolver as ti
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import str_to_dt

import math
import datetime as dt
from pages.figures import scatter, n_trace, spectrogram


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
            f'{self.filter_field}__gte': self.start_limit,
            f'{self.filter_field}__lte': self.stop_limit,
        }
        self.queryset = self.data_class.objects.filter(**kwargs).order_by(self.filter_field)
    
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
        if not self.queryset.exists():
            return

        rows = list(self.queryset.values_list(*self.all_fields))
        columns = list(zip(*rows))

        self.arrays = [
            np.array(column, dtype=object)
            if any(isinstance(value, (list, tuple)) for value in column if value is not None)
            else np.array(column)
            for column in columns
        ]

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

        dynamic_field = variable.dynamic.first()
        if dynamic_field is None:
            raise ValueError(f"Dynamic field for variable '{variable.name}' not found")

        self.y_db_field = dynamic_field.field_name

        self.component_indexes = [0, 1, 2] if variable.dims == 1 and variable.dim_sizes == 3 else [None]

        self.y_fields = [self.y_db_field] * len(self.component_indexes)

        self.y_arrays = []
        
        self.invalid_values = []
        
        self.figure = None


    @staticmethod
    def _extract_array_component(array_column, component_index):
        result = []

        for row in array_column:
            if row is None or len(row) <= component_index:
                result.append(np.nan)
                continue

            value = row[component_index]
            result.append(np.nan if value is None else value)

        return np.array(result, dtype=float)


    def _get_full_value_array(self, query, component_index):
        field_index = query.all_fields.index(self.y_db_field)
        full_value_array = query.arrays[field_index]

        if component_index is None:
            return full_value_array.astype(self.y_field_numpy_type)

        return self._extract_array_component(full_value_array, component_index)


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
        for component_index in self.component_indexes:
            full_value_array = self._get_full_value_array(query, component_index)

            if np.isnan(full_value_array).all():
                self.y_arrays.append([])
            else:
                self.y_arrays.append(full_value_array)

        # applying validation index in case of no aggregation is a little harder:
        # the only way to skip values when plotting is skipping index in both x_array and y_array at the same index
        # but there is a single x array and y arrays could have different validation indexes so i have to have multiple x_arrays or apply aggregation when plotting
        # chose the second option

    def get_agg_x_array(self):
        self.x_field_array = np.array(list(map(it, self.bin_centers_array)))

    # definitely could reduce # of steps here
    def get_agg_y_arrays(self, query):
        for i, component_index in enumerate(self.component_indexes):
            full_value_array = self._get_full_value_array(query, component_index)

            # getting an index of nans in value array
            mask = ~np.isnan(full_value_array)

            # getting an index of invalid values
            validation_index = self.validation_index(full_value_array, field_index=i)
            if validation_index is not None and validation_index.any():
                mask = mask & ~validation_index

            # getting maps for only non-nans
            val_bin_map = query.bin_map[mask]
            # getting only non-nans
            val_array = full_value_array[mask]

            idx, pos, counts = np.unique(val_bin_map, return_index=True, return_counts=True)

            # if no aggregation groups survived - no points on the plot
            if idx.shape[0] == 0:
                print(f"no data in field {self.y_db_field}, out of {self.variable.name} {self.variable.dataset}")
                self.y_arrays.append([])
                continue

            # getting sums for groups
            sums = np.add.reduceat(val_array, pos, axis=0)
            means = sums / counts

            result = np.full(self.x_field_array.shape, np.nan, dtype=float)
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


class SpectrogramPlot():

    def __init__(self, t_start, t_stop, variable, validate):
        self.t_start = t_start
        self.t_stop = t_stop
        self.variable = variable
        self.validate = validate

        self.x_axis = None

        self.y_axis = None
        self.y_axis_label = None
        self.y_scaletyp = None

        # z_matrix[i][j] value at time i for energy j
        self.z_matrix = None

        self.aggregation = False
        self.invalid_values = []
        self.figure = None

        self.bin_instance = None
    
    def load_data(self):
        dataset = self.variable.dataset
        data_class = dataset.dynamic.resolve_class()

        if data_class is None:
            return

        # time field from depend_0
        if not self.variable.depend_0:
            return

        try:
            depend_0_var = dataset.variables.get(name=self.variable.depend_0)
            filter_field = depend_0_var.dynamic.first().field_name
        except Exception:
            return

        # spectrogram data field
        data_field = self.variable.dynamic.filter(is_array_field=True).first()
        if data_field is None:
            return

        i_start = ti(self.t_start)
        i_stop = ti(self.t_stop)

        qs = data_class.objects.filter(**{
            f'{filter_field}__gte': i_start,
            f'{filter_field}__lte': i_stop,
            f'{data_field.field_name}__isnull': False,
        }).order_by(filter_field).values_list(filter_field, data_field.field_name)

        times = []
        values = []
        for t_val, arr_val in qs.iterator():
            times.append(t_val)
            values.append(arr_val)

        if not times:
            return

        time_array = np.array(times)              # (N,)
        z_matrix = np.array(values, dtype=float)  # (N, M)

        self._apply_validation(z_matrix)

        if len(time_array) > Bin.PPP:
            self.bin_instance = Bin(self.t_start, self.t_stop)
            time_array, z_matrix = self._aggregate(time_array, z_matrix)
            self.aggregation = True

        self.x_axis = np.array(list(map(it, time_array)))
        self.z_matrix = z_matrix

        # energies from depend_1
        if self.variable.depend_1:
            self._load_energy_axis(dataset, data_class)
        else:
            self.y_axis = np.arange(z_matrix.shape[1], dtype=float)
            self.y_scaletyp = None
    
    def _load_energy_axis(self, dataset, data_class):
        try:
            energy_var = dataset.variables.get(name=self.variable.depend_1)

            if energy_var.is_nrv():
                nrv_entry = dataset.nrv_data.filter(variable=energy_var).first()
                if nrv_entry is None or nrv_entry.value is None:
                    raise ValueError(f"NRV entry for '{energy_var.name}' not found")
                
                self.y_axis = np.array(nrv_entry.value, dtype=float)
                try:
                    self.y_axis_label = energy_var.get_axis_label() or energy_var.name
                except Exception:
                    self.y_axis_label = energy_var.name
                self.y_scaletyp = getattr(energy_var, 'scaletyp', None)
                return
        
            energy_field = energy_var.dynamic.filter(is_array_field=True).first()

            if energy_field is None:
                raise ValueError("Energy variable has no ArrayField")

            energy_values = data_class.objects.filter(
                **{f'{energy_field.field_name}__isnull': False}
            ).values_list(energy_field.field_name, flat=True).first()

            if energy_values:
                self.y_axis = np.array(energy_values, dtype=float)
                try:
                    label = energy_var.get_axis_label()
                    self.y_axis_label = label if label else energy_var.name
                except Exception:
                    self.y_axis_label = energy_var.name
                self.y_scaletyp = getattr(energy_var, 'scaletyp', None)
            else:
                raise ValueError("No energy data found")

        except Exception:
            if self.z_matrix is not None:
                self.y_axis = np.arange(self.z_matrix.shape[1], dtype=float)
            else:
                self.y_axis = np.array([0])
            self.y_scaletyp = None

    def _apply_validation(self, z_matrix):
        if not self.validate or z_matrix is None or z_matrix.size == 0:
            return

        sample = z_matrix.flat[0]
        n_channels = z_matrix.shape[1]

        if self.variable.validmin is not None:
            vmin = self.variable.validmin
            if isinstance(vmin, list):
                vmin_arr = np.array([
                    float(DataType.proper_type(v, sample) or -np.inf)
                    for v in vmin[:n_channels]
                ], dtype=float)
                z_matrix[z_matrix < vmin_arr] = np.nan
            else:
                vmin_val = DataType.proper_type(vmin, sample)
                if vmin_val is not None:
                    z_matrix[z_matrix < float(vmin_val)] = np.nan

        if self.variable.validmax is not None:
            vmax = self.variable.validmax
            if isinstance(vmax, list):
                vmax_arr = np.array([
                    float(DataType.proper_type(v, sample) or np.inf)
                    for v in vmax[:n_channels]
                ], dtype=float)
                z_matrix[z_matrix > vmax_arr] = np.nan
            else:
                vmax_val = DataType.proper_type(vmax, sample)
                if vmax_val is not None:
                    z_matrix[z_matrix > float(vmax_val)] = np.nan

        total = z_matrix.size
        nan_count = int(np.isnan(z_matrix).sum())
        self.invalid_values.append(f"{nan_count} / {total} invalid/missing")

    def _aggregate(self, time_array, z_matrix):
        n = len(time_array)
        bin_size = max(1, n // Bin.PPP)

        starts = np.arange(0, n, bin_size)
        
        counts = np.diff(np.append(starts, n)).astype(float)

        time_sums = np.add.reduceat(time_array.astype(float), starts)
        agg_times = (time_sums / counts).astype(time_array.dtype)

        z_nan_mask = np.isnan(z_matrix)
        z_filled = np.where(z_nan_mask, 0.0, z_matrix)
        z_valid_count = (~z_nan_mask).astype(float)

        z_sums = np.add.reduceat(z_filled, starts, axis=0)
        z_counts = np.add.reduceat(z_valid_count, starts, axis=0)

        z_counts[z_counts == 0] = np.nan
        agg_z = z_sums / z_counts

        return agg_times, agg_z

    def get_figure(self):
        self.figure = spectrogram(self)
