from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import User, UserProfile


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ['id', 'openid', 'username', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active']
    search_fields = ['openid', 'username', 'phone']
    readonly_fields = ['openid', 'unionid', 'created_at', 'updated_at']


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ['user', 'nickname', 'points', 'created_at']
    search_fields = ['user__openid', 'nickname']
