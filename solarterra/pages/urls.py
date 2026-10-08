from django.urls import path
from pages import views
from pages import search_views


urlpatterns = [
    path('', views.main_page, name="main_page"),
 
    # metadata
    path('data_info', views.data_info, name="data"),
    path('upload_info/<uuid:upload_id>', views.upload_info, name="upload"),
    path('variable_info/<uuid:variable_id>', views.variable_info, name="variable"),
    
    # search, export and plotting
    path('missions', search_views.select_missions, name="select_missions"),
    path('variables', search_views.select_variables, name="select_variables"),
    path('plot', search_views.plot_clicked, name="plot_clicked"),
    path('export', search_views.export_clicked, name="export_clicked"), #is a placeholder for more complex logic, gets a file responce anyway 
    
    # technical data
    path('system_data', views.system_data, name="system_data"),
    path('logs', views.logs, name="logs"),
]
