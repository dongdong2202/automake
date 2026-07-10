from django.urls import path
from . import views

urlpatterns = [
    path('store/<int:store_id>', views.StoreMenuView.as_view(), name='store-menu'),
    path('device/categories', views.DeviceMenuCategoriesQueryView.as_view(), name='device-menu-categories'),
]
