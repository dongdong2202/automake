"""
门店模块视图

接口列表：
- GET /api/store/list        获取门店列表（公开，无需登录）
- GET /api/store/{id}/       获取单个门店详情
"""

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from utils.response import ok, error
from .models import Store
from .serializers import StoreListSerializer, StoreDetailSerializer


class StoreListView(APIView):
    """
    门店列表接口

    GET /api/store/list
    返回所有营业中（status=open）的门店列表。
    小程序端通过此接口展示可选门店，支持按经纬度排序（前端计算）。
    """
    permission_classes = [AllowAny]  # 门店列表无需登录

    def get(self, request):
        # 只返回营业中的门店，按排序权重升序
        stores = Store.objects.filter(status=Store.STATUS_OPEN).order_by('sort_order', 'id')
        serializer = StoreListSerializer(stores, many=True)
        return ok(serializer.data)


class StoreDetailView(APIView):
    """
    门店详情接口

    GET /api/store/{store_id}/
    返回指定门店的详细信息（含营业时间、描述等）。
    """
    permission_classes = [AllowAny]

    def get(self, request, store_id):
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return error('门店不存在', code=2001, status=404)

        serializer = StoreDetailSerializer(store)
        return ok(serializer.data)
