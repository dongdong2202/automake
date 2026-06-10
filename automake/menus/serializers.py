"""
菜单模块序列化器
"""

from rest_framework import serializers
from .models import MenuCategory, MenuItem, MenuSku


class MenuSkuSerializer(serializers.ModelSerializer):
    """SKU 规格序列化器"""
    final_price = serializers.IntegerField(read_only=True)

    class Meta:
        model = MenuSku
        fields = ['id', 'name', 'attributes', 'price_delta', 'final_price', 'is_active', 'sort_order']


class MenuItemSerializer(serializers.ModelSerializer):
    """
    商品序列化器（含 SKU 列表）
    小程序端通过 skus 字段展示规格选择。
    """
    skus = MenuSkuSerializer(many=True, read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            'id', 'name', 'description', 'image_url',
            'base_price', 'stock_type', 'is_active',
            'sort_order', 'skus',
        ]


class MenuCategorySerializer(serializers.ModelSerializer):
    """分类序列化器（含商品列表）"""
    items = serializers.SerializerMethodField()

    class Meta:
        model = MenuCategory
        fields = ['id', 'name', 'icon_url', 'sort_order', 'items']

    def get_items(self, obj):
        # 只返回上架的商品
        active_items = obj.items.filter(is_active=True).order_by('sort_order', 'id')
        return MenuItemSerializer(active_items, many=True).data


class StoreMenuSerializer(serializers.Serializer):
    """
    门店完整菜单序列化器
    返回结构：{ categories: [...], store_id: ..., store_name: ... }
    """
    store_id = serializers.IntegerField()
    store_name = serializers.CharField()
    categories = MenuCategorySerializer(many=True)
