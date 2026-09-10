import logging
from rest_framework.views import APIView
from utils.permissions import IsSuperAdmin
from utils.response import ok, error
from users.models import User
from stores.models import Store
from ..serializers import UserAdminSerializer
from ..filters import StandardPagination

logger = logging.getLogger(__name__)



class UserAdminListView(APIView):
    """
    GET  /api/admin/users/ - 运营人员/管理员列表（超管专属）
    POST /api/admin/users/ - 创建新管理员账号（超管专属）
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        qs = User.objects.filter(role__in=[User.SUPER_ADMIN, User.ADMIN, User.MATERIAL_ADMIN]).prefetch_related('stores').order_by('-created_at')
        role = request.query_params.get('role')
        search = request.query_params.get('search', '').strip()

        if role:
            qs = qs.filter(role=role)
        if search:
            qs = qs.filter(username__icontains=search) | qs.filter(phone__icontains=search)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = UserAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()
        role = request.data.get('role', User.ADMIN)
        phone = request.data.get('phone', '').strip()
        store_ids = request.data.get('stores', [])

        if not username or not password:
            return error('用户名和密码不能为空', code=4001)

        if User.objects.filter(username=username).exists():
            return error('用户名已存在', code=4002)

        user = User.objects.create(
            username=username,
            role=role,
            phone=phone,
            is_staff=True,
            is_active=True
        )
        user.set_password(password)
        user.save()

        if store_ids:
            stores = Store.objects.filter(id__in=store_ids)
            user.stores.set(stores)

        logger.info("Admin created user: id=%s, username=%s, role=%s by superadmin=%s",
                    user.id, user.username, user.role, request.user)
        return ok(UserAdminSerializer(user).data, message='管理员账号创建成功')



class UserAdminDetailView(APIView):
    """
    GET    /api/admin/users/<int:pk>/ - 管理员详情
    PUT    /api/admin/users/<int:pk>/ - 编辑管理员账号（重置密码、修改角色、绑定门店）
    DELETE /api/admin/users/<int:pk>/ - 禁用或删除管理员账号
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return error('用户不存在', code=4041)
        return ok(UserAdminSerializer(user).data)

    def put(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if not user:
            return error('用户不存在', code=4041)

        password = request.data.get('password', '').strip()
        role = request.data.get('role')
        phone = request.data.get('phone')
        is_active = request.data.get('is_active')
        store_ids = request.data.get('stores')

        if password:
            user.set_password(password)
        if role:
            user.role = role
        if phone is not None:
            user.phone = phone
        if is_active is not None:
            user.is_active = bool(is_active)

        user.save()

        if store_ids is not None:
            stores = Store.objects.filter(id__in=store_ids)
            user.stores.set(stores)

        logger.info("Admin updated user: pk=%s by superadmin=%s", pk, request.user)
        return ok(UserAdminSerializer(user).data, message='管理员账号更新成功')

    def delete(self, request, pk):
        if request.user.id == pk:
            return error('不能删除当前登录的超级管理员自身', code=4003)

        user = User.objects.filter(pk=pk).first()
        if not user:
            return error('用户不存在', code=4041)

        user.is_active = False
        user.save(update_fields=['is_active'])
        logger.warning("Admin disabled user: pk=%s by superadmin=%s", pk, request.user)
        return ok(message='账号已禁用')

