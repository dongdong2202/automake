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

    # 支付模块
    path('api/pay/', include('payments.urls')),

    # 设备模块（上位机调用）
    path('api/device/', include('devices.urls')),

    # 消息通知模块（取餐码、订单状态查询、事件告警）
    path('api/notify/', include('notifications.urls')),


    # 上位机模拟器
    path('simulator/', include('simulator.urls')),

    # OpenAPI 接口 Schema 生成
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[AllowAny]), name='schema'),
    # Swagger UI 接口文档（图形化测试接口）
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[AllowAny]), name='swagger-ui'),
    # ReDoc 备用接口文档
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[AllowAny]), name='redoc'),
]
