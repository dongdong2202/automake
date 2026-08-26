from django.urls import path
from . import views
from devices.views import DeviceOrderPendingCheckView

urlpatterns = [
    path('check_pending', DeviceOrderPendingCheckView.as_view(), name='order-check-pending'),
    path('status/check', DeviceOrderPendingCheckView.as_view(), name='order-status-check'),
    path('precheck', views.OrderPrecheckView.as_view(), name='order-precheck'),
    path('create', views.OrderCreateView.as_view(), name='order-create'),
    path('list', views.OrderListView.as_view(), name='order-list'),
    path('<str:order_no>', views.OrderDetailView.as_view(), name='order-detail'),
    path('<str:order_no>/cancel', views.OrderCancelView.as_view(), name='order-cancel'),
    path('<str:order_no>/invoice', views.OrderInvoiceView.as_view(), name='order-invoice'),
]
