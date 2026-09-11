"""
自定义权限类

基于 DRF Permission，实现三级角色控制：
- IsSuperAdmin：仅超级管理员
- IsAdmin：管理员及以上
- IsMaterialAdmin：物料员及以上
- IsAdminOrMaterialAdmin：管理员或物料员
- IsCustomer：普通用户（已登录）
"""

from rest_framework.permissions import BasePermission, IsAdminUser


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
            and (request.user.is_admin or request.user.is_super_admin or request.user.is_staff)
        )


class IsMaterialAdmin(BasePermission):
    """
    物料员及以上可访问（物料员 + 超级管理员）
    """
    message = '需要物料管理权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (request.user.is_super_admin or request.user.is_material_admin)
        )


class IsAdminOrMaterialAdmin(BasePermission):
    """
    管理员或物料员可访问
    """
    message = '需要管理员或物料管理权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_super_admin
                or request.user.is_admin
                or request.user.is_material_admin
                or request.user.is_staff
            )
        )


class IsCoordinator(BasePermission):
    """
    协调员及以上可访问（协调员 + 超级管理员）
    """
    message = '需要协调员管理权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (request.user.is_super_admin or getattr(request.user, 'is_coordinator', False))
        )


class IsAdminOrCoordinator(BasePermission):
    """
    管理员或协调员可访问
    """
    message = '需要管理员或协调员权限'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_super_admin
                or getattr(request.user, 'role', '') in ('admin', 'coordinator', 'super_admin')
                or request.user.is_staff
            )
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
