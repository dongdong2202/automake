"""
门店模块序列化器
"""

from rest_framework import serializers
from .models import Store


class StoreListSerializer(serializers.ModelSerializer):
    """门店列表序列化器（精简字段，用于列表展示）"""

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'address', 'lat', 'lng',
            'contact_phone', 'status', 'cover_image',
            'business_hours', 'sort_order',
        ]


class StoreDetailSerializer(serializers.ModelSerializer):
    """门店详情序列化器（完整信息）"""

    class Meta:
        model = Store
        fields = '__all__'
