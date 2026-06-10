"""
自定义权限类

基于 DRF Permission，实现三级角色控制：
- IsSuperAdmin：仅超级管理员
- IsAdmin：管理员及以上
- IsCustomer：普通用户（已登录）
"""

from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """
    仅超级管理员可访问
    """
    message = '需要超级管理员权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_super_admin
        )


class IsAdmin(BasePermission):
    """
    管理员及以上可访问（管理员 + 超级管理员）
    """
    message = '需要管理员权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_admin
        )


class IsCustomer(BasePermission):
    """
    已登录的普通用户（客户）可访问
    """
    message = '请先登录'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
        )
