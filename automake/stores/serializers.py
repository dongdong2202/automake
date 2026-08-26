"""
门店模块序列化器
"""

from rest_framework import serializers
from .models import Store


class StoreListSerializer(serializers.ModelSerializer):
    """门店列表序列化器（精简字段，用于列表展示）"""
    device_sn = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'address', 'lat', 'lng',
            'contact_phone', 'status', 'cover_image',
            'business_hours', 'sort_order', 'code', 'device_sn',
            'is_in_business_hours'
        ]

    def get_device_sn(self, obj):
        dev = obj.devices.first()
        return dev.device_sn if dev else (obj.code or f"DEV_{obj.id}")


class StoreDetailSerializer(serializers.ModelSerializer):
    """门店详情序列化器（完整信息）"""
    device_sn = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = '__all__'

    def get_device_sn(self, obj):
        dev = obj.devices.first()
        return dev.device_sn if dev else (obj.code or f"DEV_{obj.id}")
