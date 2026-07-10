from django.urls import path
from . import views

urlpatterns = [
    path('register', views.DeviceRegisterView.as_view(), name='device-register'),
    path('inventory/lock', views.DeviceInventoryLockView.as_view(), name='device-inventory-lock'),
    path('inventory/deduct', views.DeviceInventoryDeductView.as_view(), name='device-inventory-deduct'),
    path('inventory/release', views.DeviceInventoryReleaseView.as_view(), name='device-inventory-release'),
    path('inventory/report', views.DeviceInventoryReportView.as_view(), name='device-inventory-report'),
    path('status/report', views.DeviceHeartbeatView.as_view(), name='device-status-report'),
    path('order/status/report', views.DeviceOrderStatusReportView.as_view(), name='device-order-status'),
    path('consumable/query', views.DeviceConsumableQueryView.as_view(), name='device-consumable-query'),
    path('config/query', views.DeviceConfigQueryView.as_view(), name='device-config-query'),
    path('soft_conf/query', views.DeviceSoftConfQueryView.as_view(), name='device-soft-conf-query'),
    path('menu_material/query', views.DeviceMenuMaterialQueryView.as_view(), name='device-menu-material-query'),
]
