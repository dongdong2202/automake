"""
monitor/serializers.py —— 设备监控快照序列化器

将 DeviceMonitorSnapshot 模型数据序列化为 API 响应格式，
额外附加 display_status 字段供前端直接读取展示状态。
"""

from rest_framework import serializers
from .models import DeviceMonitorSnapshot


class DeviceMonitorSnapshotSerializer(serializers.ModelSerializer):
    """
    设备监控快照序列化器

    display_status 字段含义：
      - 'normal':  绿色正常
      - 'warning': 红色警告（有异常但未断线）
      - 'fault':   红色闪烁故障（断线或严重故障）
    """

    # 从 model property 读取展示状态，只读字段
    display_status = serializers.CharField(read_only=True)

    class Meta:
        model = DeviceMonitorSnapshot
        fields = [
            'device_sn',
            'healthy',
            'disconnected',
            'last_time',
            'mem_size',
            'abnormality',
            'display_status',
            'reported_at',
        ]
