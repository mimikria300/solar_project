
from pages.figures import scatter, n_trace
from solarterra.utils import bigint_ts_resolver as its

import pandas as pd
import numpy as np
import datetime as dt
import math
from pages.datawork_instances import Bin, Plot, DBQuery
from load_cdf.models import DynamicField


def get_plots(variables, t_start, t_end, validate):
     
    # do the work with the the bin
    Plot.t_start = t_start
    Plot.t_stop = t_end
    bin_instance = Bin(t_start, t_end)
    plots = []

    for item in variables.order_by('dataset__tag').distinct('dataset__tag', 'depend_0'):

        #print(item.dataset, item.depend_0)
        vars_in_query = variables.filter(dataset=item.dataset, depend_0=item.depend_0).order_by('name')

        if item.depend_0 is None:
            print(f"No dependent axis specified for dataset '{item.dataset}', vars '{vars_in_query}'! Skipping")
            continue
        
        filter_field = item.get_depend_field().field_name
        fields = list(DynamicField.objects.filter(variable_instance__in=vars_in_query).values_list('field_name', flat=True))
    
        query = DBQuery(
                dataset=item.dataset,
                filter_field=filter_field,
                t_start=t_start,
                t_stop=t_end,
                fields=fields)
        
        # creating the query
        query.query()
        has_data = query.queryset.exists()
        aggregation = False
        # if queryset is not empty
        if has_data:
            # queryset evaluation
            query.set_var_arrays()
            # HERE is the place to decide if there will be binning or not
            aggregation = True if query.get_var_array_len() > Bin.PPP else False


        # need to generate plot spaces, even if there is not data for a plot
        for var in vars_in_query:
            plot = Plot(
                    t_start=t_start,
                    t_stop=t_end,
                    variable=var,
                    x_field=filter_field,
                    validate=validate)
            
            # no computations if there isn`t any data
            if has_data:

                if aggregation:
                    plot.prepare_bins(bin_instance)
                    query.set_bin_map(plot.bin_starts_array)
            
                plot.aggregation = aggregation
                plot.set_arrays(query)

            # get the plotly figure
            plot.get_figure()
            #print(plot.variable.name, plot.bin_size)
            plots.append(plot)
        
    return plots
