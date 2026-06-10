from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('login', views.WechatLoginView.as_view(), name='user-login'),
    path('profile', views.UserProfileView.as_view(), name='user-profile'),
    path('token/refresh', TokenRefreshView.as_view(), name='token-refresh'),
]
