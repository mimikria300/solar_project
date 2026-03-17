from load_cdf.models import DynamicField
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as ti
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
        self.arrays = None

        # bin mapping over over the array of epochs
        self.bin_map = None

    def query(self):
        kwargs = {
            "{0}__gte".format(self.filter_field): self.start_limit,
            "{0}__lte".format(self.filter_field): self.stop_limit,
        }
        self.queryset = self.data_class.objects.filter(**kwargs)

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
