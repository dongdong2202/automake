from django.urls import path
from . import staff_views

urlpatterns = [
    path('devices', staff_views.StaffDeviceListView.as_view(), name='staff-device-list'),
    path('devices/<str:device_sn>/stock', staff_views.StaffDeviceStockView.as_view(), name='staff-device-stock'),
    path('devices/<str:device_sn>/action', staff_views.StaffDeviceActionView.as_view(), name='staff-device-action'),
    path('consumables/update', staff_views.StaffConsumableUpdateView.as_view(), name='staff-consumables-update'),
]
