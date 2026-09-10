import logging
from rest_framework.views import APIView
from utils.permissions import IsAdmin, IsSuperAdmin
from utils.response import ok, error
from global_config.models import DeviceModel
from ..serializers import DeviceModelSerializer

logger = logging.getLogger(__name__)


class DeviceModelListView(APIView):
    """
    GET  /api/admin/global-config/device-models/ - 获取设备型号列表
    POST /api/admin/global-config/device-models/ - 创建设备型号（超管专属）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        models = DeviceModel.objects.all().order_by('id')
        serializer = DeviceModelSerializer(models, many=True)
        return ok(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可创建设备型号', code=4031)

        serializer = DeviceModelSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        model = serializer.save()
        logger.info("Admin created DeviceModel: id=%s, code=%s, name=%s by user=%s",
                    model.id, model.code, model.name, request.user)
        return ok(DeviceModelSerializer(model).data, message='设备型号创建成功')



class DeviceModelDetailView(APIView):
    """
    GET    /api/admin/global-config/device-models/<int:pk>/ - 型号详情
    PUT    /api/admin/global-config/device-models/<int:pk>/ - 更新型号
    DELETE /api/admin/global-config/device-models/<int:pk>/ - 删除型号
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        model = DeviceModel.objects.filter(pk=pk).first()
        if not model:
            return error('设备型号不存在', code=4041)
        return ok(DeviceModelSerializer(model).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改设备型号', code=4031)

        model = DeviceModel.objects.filter(pk=pk).first()
        if not model:
            return error('设备型号不存在', code=4041)

        serializer = DeviceModelSerializer(model, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        updated_model = serializer.save()
        logger.info("Admin updated DeviceModel: pk=%s by user=%s", pk, request.user)
        return ok(DeviceModelSerializer(updated_model).data, message='设备型号更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除设备型号', code=4031)

        model = DeviceModel.objects.filter(pk=pk).first()
        if not model:
            return error('设备型号不存在', code=4041)

        if model.devices.exists():
            return error('已有设备绑定该型号，禁止直接删除。请先调整相关设备型号', code=4002)

        if model.categories.exists():
            return error('已有菜单品类分类关联该型号，禁止直接删除。请先删除或转移分类', code=4003)

        model.delete()
        logger.warning("Admin deleted DeviceModel: pk=%s by user=%s", pk, request.user)
        return ok(message='设备型号已删除')

