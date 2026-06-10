"""
菜单模块视图

接口列表：
- GET /api/menu/store/{store_id}    获取门店完整菜单（含分类、商品、规格）
"""

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from utils.response import ok, error
from stores.models import Store
from .models import MenuCategory
from .serializers import MenuCategorySerializer


class StoreMenuView(APIView):
    """
    门店菜单接口

    GET /api/menu/store/{store_id}
    返回指定门店的完整菜单（分类 → 商品 → 规格/SKU）。
    前置依赖：门店必须存在且处于营业状态。
    使用 select_related/prefetch_related 减少查询次数（避免 N+1 问题）。
    """
    permission_classes = [AllowAny]  # 浏览菜单无需登录

    def get(self, request, store_id):
        # 检查门店是否存在且营业
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return error('门店不存在', code=3001, status=404)

        if not store.is_open:
            return error('门店暂未营业', code=3002, status=400)

        # 使用 prefetch_related 一次性加载分类、商品、SKU，避免 N+1
        categories = (
            MenuCategory.objects
            .filter(store=store, is_active=True)
            .prefetch_related(
                'items',           # 预加载商品
                'items__skus',     # 预加载 SKU
            )
            .order_by('sort_order', 'id')
        )

        category_data = MenuCategorySerializer(categories, many=True).data

        return ok({
            'store_id': store.id,
            'store_name': store.name,
            'categories': category_data,
        })
