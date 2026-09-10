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
    path('poster', views.DevicePosterQueryView.as_view(), name='device-poster'),
    path('order/check_pending', views.DeviceOrderPendingCheckView.as_view(), name='device-order-check-pending'),
    path('guide/check', views.DeviceGuideCheckView.as_view(), name='device-guide-check'),
    path('order/batch_refund', views.DeviceBatchRefundView.as_view(), name='device-order-batch-refund'),
    path('order/refund', views.DeviceBatchRefundView.as_view(), name='device-order-refund'),
    path('batch_refund', views.DeviceBatchRefundView.as_view(), name='device-batch-refund'),
    path('conf1', views.DeviceConf1View.as_view(), name='device-conf1'),
    path('conf1/<str:device_sn>', views.DeviceConf1View.as_view(), name='device-conf1-by-sn'),
    path('config1', views.DeviceConf1View.as_view(), name='device-config1'),
    path('config1/<str:device_sn>', views.DeviceConf1View.as_view(), name='device-config1-by-sn'),
    path('config', views.DeviceUnifiedConfigView.as_view(), name='device-unified-config'),
    path('conf', views.DeviceUnifiedConfigView.as_view(), name='device-unified-conf'),
]
