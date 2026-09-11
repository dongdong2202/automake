from django.urls import path
from . import views

urlpatterns = [
    # 小程序 JSAPI 支付
    path('create', views.PayCreateView.as_view(), name='pay-create'),
    # Native 扫码支付 (主扫)
    path('wechat/native', views.PayNativeCreateView.as_view(), name='pay-wechat-native'),
    path('wechat/native/<str:order_id>', views.PayNativeCreateView.as_view(), name='pay-wechat-native-with-id'),
    # 付款码支付 (被扫)
    path('wechat/codepay', views.PayCodePayView.as_view(), name='pay-wechat-codepay'),
    # 状态查询
    path('status/<str:order_no>', views.PayStatusQueryView.as_view(), name='pay-status-query'),
    path('status', views.PayStatusQueryView.as_view(), name='pay-status-query-param'),
    # 微信异步回调
    path('callback', views.PayCallbackView.as_view(), name='pay-callback'),
    path('refund', views.PayRefundView.as_view(), name='pay-refund'),
]
