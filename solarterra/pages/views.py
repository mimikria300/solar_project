from django.shortcuts import render
from load_cdf.models import * 
from data_cdf.models import *
from django.http import Http404
from django.apps import apps
from solarterra.utils import bigint_ts_resolver
from django.db.models import Max, Min
from django.conf import settings
from django.db import connection


def main_page(request):
    template = "pages/main.html"
    context = {"main_page": True}
    return render(request, template, context)


def system_data(request):
    template = "pages/system_data.html"
    cursor = connection.cursor()
    cursor.execute('select version();')
    row = cursor.fetchone()
    context = {
        'version': settings.PROJECT_VERSION,
        'path': settings.BASE_DIR,
        'hashsum': '',
        'db_version': row[0],

    }

    return render(request, template, context)

def data_info(request):
    return render(request, "pages/data_official.html", context={'datasets': Dataset.objects.order_by('tag')})

def upload_info(request, upload_id):
    upload = Upload.objects.get_or_none(id=upload_id)
    if upload is None:
        raise Http404
    return render(request, "pages/upload_data.html", context={'upload': upload})

def variable_info(request, variable_id):
    var = Variable.objects.get_or_none(id=variable_id)
    if var is None:
        raise Http404
    return render(request, "pages/variable_data.html", context={'variable': var})


def logs(request):
    template = "pages/logs.html"
    context = {}
    context['logs'] = LogEntry.objects.order_by('-timestamp')
    return render(request, template, context)
