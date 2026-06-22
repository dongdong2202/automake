from django.urls import path
from . import views

urlpatterns = [
    path('create', views.PayCreateView.as_view(), name='pay-create'),
    path('callback', views.PayCallbackView.as_view(), name='pay-callback'),
    path('mock-success', views.PayMockSuccessView.as_view(), name='pay-mock-success'),
]
