from django.shortcuts import render
from load_cdf.models import *
from data_cdf.models import *
from django.http import Http404
from django.apps import apps

from pages.forms import SourceForm
import datetime as dt

from pages.plotting import get_plots


def search(request):
    
    if request.method == 'POST':
        source_form = SourceForm(data=request.POST)
 
        if source_form.is_valid():
            print("valid!")
            # go and play, you are free, child
            var_instances = Variable.objects.filter(id__in=source_form.cleaned_data['sources'])
            t_start = source_form.cleaned_data['ts_start']
            t_stop = source_form.cleaned_data['ts_end']
            validate = source_form.cleaned_data['validate']
            plots = get_plots(var_instances, t_start, t_stop, validate)
            #bin_instance = plots[0].bin_instance
            #print("BIN INSTANCE", bin_instance, bin_instance.bin_seconds)
            """ 
            left_form = SourceForm(initial={
                't_start' : bin_instance.t_previous(t_start), 
                't_end' : t_start, 
                'sources' : source_form.cleaned_data['sources']})
            right_form = SourceForm(initial={
                't_start' : t_stop, 
                't_end' : bin_instance.t_next(t_stop), 
                'sources' : source_form.cleaned_data['sources']})
            """
            context = {
                't_start' : t_start,
                't_stop' : t_stop,
                'plots' : plots,
                #'bin_instance' : bin_instance,
                #'left_form' : left_form,
                #'right_form' : right_form
                
            }
            return render(request, "pages/plot_page.html", context=context)

        else:
            # finish page reconstruction after invalid values or do form validation client-side
            print("invalid!")
            return render(request, "pages/sources.html", context={
                'datasets' : Dataset.objects.have_data().order_by('tag'),
                'form' : source_form
            })
    else:
        return render(request, "pages/sources.html", context={
                'datasets' : Dataset.objects.have_data().order_by('tag'),
                'form' : SourceForm(initial={'ts_start' : dt.datetime(year=2013, month=1, day=1, hour=1), 'ts_end' : dt.datetime(year=2013, month=12, day=30, hour=1)}),
                'fresh' : True
        })