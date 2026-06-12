from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import User, UserProfile


class ReadOnlyStoreScopedUserAdmin(ModelAdmin):
    """
    用户及基本档案只读且只限本门店的后台管理基类
    """
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if request.user.store:
                if self.model == User:
                    return qs.filter(store=request.user.store)
                elif self.model == UserProfile:
                    return qs.filter(user__store=request.user.store)
            return qs.none()
        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            if obj is not None:
                if self.model == User:
                    if obj.store != request.user.store:
                        return False
                elif self.model == UserProfile:
                    if obj.user.store != request.user.store:
                        return False
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return False
        return super().has_delete_permission(request, obj)

    def has_module_permission(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'admin':
            return True
        return super().has_module_permission(request)


@admin.register(User)
class UserAdmin(ReadOnlyStoreScopedUserAdmin):
    list_display = ['id', 'openid', 'username', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active']
    search_fields = ['openid', 'username', 'phone']
    readonly_fields = ['openid', 'unionid', 'created_at', 'updated_at']

    fieldsets = (
        ('登录凭据与基本信息', {
            'fields': ('username', 'password', 'phone', 'role', 'store')
        }),
        ('状态与权限控制', {
            'fields': ('is_active', 'is_staff', 'is_superuser')
        }),
        ('微信关联信息（只读）', {
            'fields': ('openid', 'unionid')
        }),
    )

    def save_model(self, request, obj, form, change):
        # 自动哈希化管理员在后台手动输入的明文密码
        if obj.password and not (obj.password.startswith('pbkdf2_sha256$') or obj.password.startswith('argon2$') or obj.password.startswith('bcrypt$')):
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)


@admin.register(UserProfile)
class UserProfileAdmin(ReadOnlyStoreScopedUserAdmin):
    list_display = ['user', 'nickname', 'points', 'created_at']
    search_fields = ['user__openid', 'nickname']
