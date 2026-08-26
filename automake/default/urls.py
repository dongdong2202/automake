"""
主 URL 路由配置

API 路由结构：
  /api/user/          用户相关（登录、资料）
  /api/store/         门店相关
  /api/menu/          菜单相关
  /api/order/         订单相关
  /api/pay/           支付相关
  /api/device/        设备相关（上位机调用）
  /admin/             Django 后台管理
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework.permissions import AllowAny
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from django.conf import settings
from django.conf.urls.static import static

from django.views.generic import TemplateView
from django.urls import re_path
from django.views.static import serve

urlpatterns = [
    # Django 管理后台
    path('admin/', admin.site.urls),

    # 用户模块：登录、资料
    path('api/user/', include('users.urls')),

    # JWT Token 刷新（用户模块中已包含）

    # 门店模块
    path('api/store/', include('stores.urls')),

    # 菜单模块
    path('api/menu/', include('menus.urls')),

    # 订单模块
    path('api/order/', include('orders.urls')),
    # 支付引导规范中指定的订单支付状态及 Native 支付别名路由
    path('api/orders/<str:order_id>/native-payment/', include([
        path('', __import__('payments.views', fromlist=['PayNativeCreateView']).PayNativeCreateView.as_view(), name='order-native-payment'),
    ])),
    path('api/orders/<str:order_id>/payment-status/', include([
        path('', __import__('payments.views', fromlist=['PayStatusQueryView']).PayStatusQueryView.as_view(), name='order-payment-status'),
    ])),
    path('api/internal/payments/wechat/codepay/', __import__('payments.views', fromlist=['PayCodePayView']).PayCodePayView.as_view(), name='internal-wechat-codepay'),
    path('api/internal/payments/<str:out_trade_no>/status/', __import__('payments.views', fromlist=['PayStatusQueryView']).PayStatusQueryView.as_view(), name='internal-wechat-status'),

    # 支付模块
    path('api/pay/', include('payments.urls')),
    path('payment-test/', __import__('payments.views', fromlist=['PaymentTestPageView']).PaymentTestPageView.as_view(), name='payment-test-page'),

    # 设备模块（上位机调用）
    path('api/device/', include('devices.urls')),

    # 消息通知模块（取餐码、订单状态查询、事件告警）
    path('api/notify/', include('notifications.urls')),

    # 设备监控与分析模块
    path('api/monitor/', include('monitor.urls')),

    # 运营管理后台与数据分析 API
    path('api/admin/', include('admin_api.urls')),

    # 移动端物料员与协调员操作 API
    path('api/staff/', include('devices.staff_urls')),

    # 上位机模拟器
    path('simulator/', include('simulator.urls')),

    # OpenAPI 接口 Schema 生成
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[AllowAny]), name='schema'),
    # Swagger UI 接口文档（图形化测试接口）
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[AllowAny]), name='swagger-ui'),
    # ReDoc 备用接口文档
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[AllowAny]), name='redoc'),

    # 前端构建产物 SPA 路由映射与 assets 资源代理
    re_path(r'^assets/(?P<path>.*)$', serve, {'document_root': settings.BASE_DIR.parent / 'frontend' / 'dist' / 'assets'}),
    re_path(r'^(?!admin|api|simulator|ws|media|static|assets|payment-test).*$', TemplateView.as_view(template_name='index.html')),
]

# 开发及生产静态媒体文件路由服务
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
