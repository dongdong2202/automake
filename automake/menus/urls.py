from django.urls import path
from . import views

urlpatterns = [
    path('store/<str:device_sn>', views.StoreMenuView.as_view(), name='store-menu'),
]
