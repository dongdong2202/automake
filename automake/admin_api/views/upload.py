import os
import uuid
import logging
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from utils.permissions import IsAdmin
from utils.response import ok, error

logger = logging.getLogger(__name__)


class FileUploadView(APIView):
    """
    POST /api/admin/upload/ - 通用文件/图片上传接口
    """
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return error('未检测到上传文件', code=4001)

        upload_type = request.data.get('type', 'posters')
        ext = os.path.splitext(file_obj.name)[1].lower()
        filename = f"{uuid.uuid4().hex[:12]}{ext}"
        relative_path = f"{upload_type}/{filename}"

        saved_path = default_storage.save(relative_path, ContentFile(file_obj.read()))
        url = default_storage.url(saved_path)

        logger.info("Admin file uploaded: path=%s, size=%s by user=%s", saved_path, file_obj.size, request.user)

        return ok({
            'url': url,
            'path': saved_path,
            'filename': file_obj.name,
            'size': file_obj.size,
        }, message='文件上传成功')

