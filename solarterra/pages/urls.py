from django.urls import path
from pages import views
from pages import search_views
import uuid

urlpatterns = [
    path('', views.main_page, name="main_page"),
 
    # metadata
    path('data_info', views.data_info, name="data"),
    path('upload_info/<uuid:upload_id>', views.upload_info, name="upload"),
    path('variable_info/<uuid:variable_id>', views.variable_info, name="variable"),
    
    # search, export and plotting
    path('search', search_views.search, name="search"),
    path('export', search_views.export, name="export"),
    path('plot', search_views.plot, name="plot"),

    # technical data
    path('system_data', views.system_data, name="system_data"),
    path('logs', views.logs, name="logs"),

]
