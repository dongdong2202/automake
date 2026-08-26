from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """标准分页类，支持前端自定义 page_size"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'code': 0,
            'message': 'success',
            'data': {
                'count': self.page.paginator.count,
                'page': self.page.number,
                'page_size': self.get_page_size(self.request),
                'total_pages': self.page.paginator.num_pages,
                'results': data
            }
        })


class StoreScopedQuerysetMixin:
    """
    数据隔离 Mixin：
    - 超级管理员：可查看所有门店数据
    - 门店管理员/物料员：仅可查看关联门店数据
    """
    store_field = 'store'  # 默认为 store 外键字段

    def get_scoped_queryset(self, qs, request):
        user = request.user
        if not user or not user.is_authenticated:
            return qs.none()

        if user.is_super_admin:
            return qs

        user_stores = user.stores.all()
        if not user_stores.exists():
            return qs.none()

        lookup = f"{self.store_field}__in"
        return qs.filter(**{lookup: user_stores})
