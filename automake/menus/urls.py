from django.urls import path
from . import views

urlpatterns = [
    # 获取设备菜单（通过设备编号 device_sn 或兼容门店 ID）
    path('store/<str:device_sn>', views.StoreMenuView.as_view(), name='store-menu'),
    path('device/<str:device_sn>', views.StoreMenuView.as_view(), name='device-menu'),
    path('device/categories', views.DeviceMenuCategoriesQueryView.as_view(), name='device-menu-categories'),
    # 饮品售罄接口（物料总量 < 10）
    path('sold-out/<str:device_sn>', views.DeviceSoldOutItemsView.as_view(), name='device-sold-out-path'),
    path('sold-out', views.DeviceSoldOutItemsView.as_view(), name='device-sold-out-query'),
    path('sold_out', views.DeviceSoldOutItemsView.as_view(), name='device-sold-out-query-underscore'),
]
