from django.urls import path
from . import views

urlpatterns = [
    path('', views.simulator_view, name='simulator_index'),
    path('api/status/', views.simulator_status_api, name='simulator_status_api'),
    path('api/logs/', views.simulator_logs_api, name='simulator_logs_api'),
    path('api/report/', views.simulator_report_api, name='simulator_report_api'),
    path('api/clear_logs/', views.simulator_clear_logs_api, name='simulator_clear_logs_api'),
    path('api/create_test_order/', views.simulator_create_test_order_api, name='simulator_create_test_order_api'),
    path('api/diagnostics/', views.simulator_diagnostics_api, name='simulator_diagnostics_api'),
]
