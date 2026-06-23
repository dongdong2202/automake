"""
monitor/views.py —— 设备监控 REST API 视图

提供：
  GET /api/monitor/devices/        —— 所有设备最新监控快照列表
  GET /api/monitor/devices/{sn}/   —— 指定设备最新监控快照
"""

import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from utils.response import ok, error
from .models import DeviceMonitorSnapshot
from .serializers import DeviceMonitorSnapshotSerializer

logger = logging.getLogger('monitor')


class DeviceMonitorListView(APIView):
    """
    GET /api/monitor/devices/
    返回所有设备的最新监控快照（包含状态、物料、异常信息）。
    需登录后访问（IsAuthenticated）。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 查询全部设备快照，按设备序列号排序
        snapshots = DeviceMonitorSnapshot.objects.all()
        serializer = DeviceMonitorSnapshotSerializer(snapshots, many=True)
        return ok(serializer.data)


class DeviceMonitorDetailView(APIView):
    """
    GET /api/monitor/devices/{sn}/
    返回指定设备序列号的最新监控快照。
    404 表示该设备尚未上报过任何状态。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, sn):
        try:
            snapshot = DeviceMonitorSnapshot.objects.get(device_sn=sn)
        except DeviceMonitorSnapshot.DoesNotExist:
            return error(f'设备 {sn} 尚无监控数据', code=4041, status=404)

        serializer = DeviceMonitorSnapshotSerializer(snapshot)
        return ok(serializer.data)
