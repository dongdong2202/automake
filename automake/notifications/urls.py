"""
消息通知模块 URL 配置
"""
from django.urls import path
from .views import (
    PickupCodeVerifyView,
    OrderStatusQueryView,
    NotifyEventListView,
    NotifyEventHandleView,
)

urlpatterns = [
    # 设备扫码核销取餐码
    path('pickup/verify/', PickupCodeVerifyView.as_view(), name='pickup-verify'),

    # 小程序轮询订单状态与等候时间
    path('order/<str:order_no>/status/', OrderStatusQueryView.as_view(), name='order-status-query'),

    # 管理员：通知事件列表
    path('events/', NotifyEventListView.as_view(), name='notify-events-list'),

    # 管理员：标记通知事件已处理
    path('events/<int:pk>/handle/', NotifyEventHandleView.as_view(), name='notify-event-handle'),
]
