import logging
from django.db import models
from rest_framework.views import APIView
from utils.permissions import IsSuperAdmin, IsAdmin
from utils.response import ok, error
from stores.models import Store
from global_config.models import (
    GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku
)
from menus.models import MenuItem, MenuSku
from ..serializers import (
    GlobalMenuCategorySerializer, GlobalMenuItemSerializer, StoreMenuItemSerializer,
    GlobalSkuTemplateSerializer, GlobalMenuSkuSerializer, StoreMenuSkuSerializer
)
from ..filters import StandardPagination

logger = logging.getLogger(__name__)


class GlobalMenuCategoryListView(APIView):
    """
    GET  /api/admin/menus/global-categories/ - 全局分类列表
    POST /api/admin/menus/global-categories/ - 创建全局分类（超管）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = GlobalMenuCategory.objects.all().select_related('device_model').order_by('sort_order', 'id')
        device_model_id = request.query_params.get('device_model')
        if device_model_id:
            qs = qs.filter(device_model_id=device_model_id)

        serializer = GlobalMenuCategorySerializer(qs, many=True)
        return ok(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可创建全局分类', code=4031)

        serializer = GlobalMenuCategorySerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[AdminMenuCatCreate] 参数校验失败: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        cat = serializer.save()
        logger.info(f"[AdminMenuCatCreate] 管理员 {request.user.username} 创建分类: id={cat.id}, name={cat.name}")
        return ok(GlobalMenuCategorySerializer(cat).data, message='分类创建成功')


class GlobalMenuCategoryDetailView(APIView):
    """
    GET    /api/admin/menus/global-categories/<int:pk>/ - 分类详情
    PUT    /api/admin/menus/global-categories/<int:pk>/ - 更新分类
    DELETE /api/admin/menus/global-categories/<int:pk>/ - 删除分类
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        cat = GlobalMenuCategory.objects.filter(pk=pk).select_related('device_model').first()
        if not cat:
            return error('分类不存在', code=4041)
        return ok(GlobalMenuCategorySerializer(cat).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改全局分类', code=4031)

        cat = GlobalMenuCategory.objects.filter(pk=pk).first()
        if not cat:
            return error('分类不存在', code=4041)

        serializer = GlobalMenuCategorySerializer(cat, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"[AdminMenuCatUpdate] 更新分类参数校验失败: id={pk}, errors={serializer.errors}")
            return error(str(serializer.errors), code=4001)

        updated_cat = serializer.save()
        logger.info(f"[AdminMenuCatUpdate] 管理员 {request.user.username} 更新分类: id={pk}, name={updated_cat.name}")
        return ok(GlobalMenuCategorySerializer(updated_cat).data, message='分类更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除全局分类', code=4031)

        cat = GlobalMenuCategory.objects.filter(pk=pk).first()
        if not cat:
            return error('分类不存在', code=4041)

        if cat.items.exists():
            return error('该分类下仍存在关联商品，禁止直接删除。请先删除或迁移商品', code=4002)

        cat_name = cat.name
        cat.delete()
        logger.info(f"[AdminMenuCatDelete] 管理员 {request.user.username} 删除分类: id={pk}, name={cat_name}")
        return ok(message='分类已删除')


class GlobalMenuItemListView(APIView):
    """
    GET  /api/admin/menus/global-items/ - 全局商品列表
    POST /api/admin/menus/global-items/ - 创建全局商品（超管）
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = GlobalMenuItem.objects.all().select_related('category').order_by('sort_order', 'id')
        category_id = request.query_params.get('category_id')
        search = request.query_params.get('search', '').strip()

        if category_id:
            qs = qs.filter(category_id=category_id)
        if search:
            qs = qs.filter(name__icontains=search)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = GlobalMenuItemSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可创建全局商品', code=4031)

        serializer = GlobalMenuItemSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"[AdminMenuItemCreate] 创建商品参数错误: {serializer.errors}")
            return error(str(serializer.errors), code=4001)

        item = serializer.save()
        logger.info(f"[AdminMenuItemCreate] 管理员 {request.user.username} 创建全局商品: id={item.id}, name={item.name}")
        return ok(GlobalMenuItemSerializer(item).data, message='全局商品创建成功')


class GlobalMenuItemDetailView(APIView):
    """
    GET    /api/admin/menus/global-items/<int:pk>/ - 获取商品详情
    PUT    /api/admin/menus/global-items/<int:pk>/ - 修改商品
    DELETE /api/admin/menus/global-items/<int:pk>/ - 删除商品
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        item = GlobalMenuItem.objects.filter(pk=pk).select_related('category', 'category__device_model').first()
        if not item:
            return error('商品不存在', code=4041)
        return ok(GlobalMenuItemSerializer(item).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改全局商品', code=4031)

        item = GlobalMenuItem.objects.filter(pk=pk).first()
        if not item:
            return error('商品不存在', code=4041)

        serializer = GlobalMenuItemSerializer(item, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"[AdminMenuItemUpdate] 更新商品参数校验失败: id={pk}, errors={serializer.errors}")
            return error(str(serializer.errors), code=4001)

        updated_item = serializer.save()
        logger.info(f"[AdminMenuItemUpdate] 管理员 {request.user.username} 更新全局商品: id={pk}, name={updated_item.name}")
        return ok(GlobalMenuItemSerializer(updated_item).data, message='商品更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除全局商品', code=4031)

        item = GlobalMenuItem.objects.filter(pk=pk).first()
        if not item:
            return error('商品不存在', code=4041)

        # 检查是否有正在生效的门店菜单绑定
        if item.local_items.filter(is_active=True).exists():
            return error('已有门店菜单上架该商品，请先将对应门店菜单下架后再删除', code=4002)

        item_name = item.name
        item.delete()
        logger.info(f"[AdminMenuItemDelete] 管理员 {request.user.username} 删除全局商品: id={pk}, name={item_name}")
        return ok(message='商品已删除')


class GlobalSkuTemplateListView(APIView):
    """
    GET  /api/admin/menus/sku-templates/ - 全局规格模板列表
    POST /api/admin/menus/sku-templates/ - 创建规格模板
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = GlobalSkuTemplate.objects.all().prefetch_related('ingredients', 'ingredients__material', 'menu_skus').order_by('category', 'sort_order', 'id')
        category = request.query_params.get('category', '').strip()
        search = request.query_params.get('search', '').strip()

        if category:
            qs = qs.filter(category=category)
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(description__icontains=search)

        serializer = GlobalSkuTemplateSerializer(qs, many=True)
        return ok(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可创建规格模板', code=4031)

        serializer = GlobalSkuTemplateSerializer(data=request.data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        tpl = serializer.save()
        return ok(GlobalSkuTemplateSerializer(tpl).data, message='规格模板创建成功')


class GlobalSkuTemplateDetailView(APIView):
    """
    GET    /api/admin/menus/sku-templates/<int:pk>/ - 规格模板详情
    PUT    /api/admin/menus/sku-templates/<int:pk>/ - 修改规格模板
    DELETE /api/admin/menus/sku-templates/<int:pk>/ - 删除规格模板
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        tpl = GlobalSkuTemplate.objects.filter(pk=pk).prefetch_related('ingredients', 'ingredients__material', 'menu_skus').first()
        if not tpl:
            return error('规格模板不存在', code=4041)
        return ok(GlobalSkuTemplateSerializer(tpl).data)

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改规格模板', code=4031)

        tpl = GlobalSkuTemplate.objects.filter(pk=pk).first()
        if not tpl:
            return error('规格模板不存在', code=4041)

        serializer = GlobalSkuTemplateSerializer(tpl, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        updated_tpl = serializer.save()
        return ok(GlobalSkuTemplateSerializer(updated_tpl).data, message='规格模板更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除规格模板', code=4031)

        tpl = GlobalSkuTemplate.objects.filter(pk=pk).first()
        if not tpl:
            return error('规格模板不存在', code=4041)

        if tpl.menu_skus.exists():
            return error('已有商品绑定该规格模板，禁止直接删除。请先解除商品规格绑定后再删除', code=4002)

        tpl.delete()
        return ok(message='规格模板已删除')


class GlobalMenuSkuListView(APIView):
    """
    GET  /api/admin/menus/global-skus/ - 获取全局所有商品规格列表（菜单规格库）
    POST /api/admin/menus/global-skus/ - 直接创建商品规格
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = GlobalMenuSku.objects.all().select_related(
            'item', 'item__category', 'template'
        ).prefetch_related(
            'ingredients', 'ingredients__material', 'template__ingredients', 'template__ingredients__material'
        ).order_by('item__sort_order', 'item_id', 'sort_order', 'id')

        item_id = request.query_params.get('item_id')
        category_id = request.query_params.get('category_id')
        template_category = request.query_params.get('template_category')
        search = request.query_params.get('search', '').strip()

        if item_id:
            qs = qs.filter(item_id=item_id)
        if category_id:
            qs = qs.filter(item__category_id=category_id)
        if template_category:
            qs = qs.filter(template__category=template_category)
        if search:
            qs = qs.filter(models.Q(item__name__icontains=search) | models.Q(template__name__icontains=search))

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = GlobalMenuSkuSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if not request.user.is_super_admin:
            return error('仅超级管理员可配置商品规格', code=4031)

        item_id = request.data.get('item') or request.data.get('item_id')
        template_id = request.data.get('template') or request.data.get('template_id')
        if not item_id or not template_id:
            return error('必须指定商品 ID 和规格模板 ID', code=4001)

        item = GlobalMenuItem.objects.filter(pk=item_id).first()
        if not item:
            return error('商品不存在', code=4041)

        template = GlobalSkuTemplate.objects.filter(pk=template_id).first()
        if not template:
            return error('规格模板不存在', code=4042)

        if GlobalMenuSku.objects.filter(item=item, template=template).exists():
            return error('该商品已绑定此规格模板，无需重复绑定', code=4003)

        price_delta = request.data.get('price_delta')
        if price_delta is None:
            price_delta = template.default_price_delta

        data = {
            'item': item.id,
            'template': template.id,
            'price_delta': price_delta,
            'is_active': request.data.get('is_active', True),
            'sort_order': request.data.get('sort_order', 0),
            'ingredients': request.data.get('ingredients', [])
        }
        serializer = GlobalMenuSkuSerializer(data=data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        sku = serializer.save()
        return ok(GlobalMenuSkuSerializer(sku).data, message='规格创建成功')


class GlobalMenuItemSkuListView(APIView):
    """
    GET  /api/admin/menus/global-items/<int:item_id>/skus/ - 获取某商品的所有SKU
    POST /api/admin/menus/global-items/<int:item_id>/skus/ - 为商品绑定规格模板
    """
    permission_classes = [IsAdmin]

    def get(self, request, item_id):
        item = GlobalMenuItem.objects.filter(pk=item_id).first()
        if not item:
            return error('商品不存在', code=4041)

        skus = item.skus.all().select_related('template').prefetch_related('ingredients', 'ingredients__material', 'template__ingredients', 'template__ingredients__material').order_by('sort_order', 'id')
        serializer = GlobalMenuSkuSerializer(skus, many=True)
        return ok(serializer.data)

    def post(self, request, item_id):
        if not request.user.is_super_admin:
            return error('仅超级管理员可配置商品规格', code=4031)

        item = GlobalMenuItem.objects.filter(pk=item_id).first()
        if not item:
            return error('商品不存在', code=4041)

        template_id = request.data.get('template_id') or request.data.get('template')
        if not template_id:
            return error('必须指定规格模板 ID', code=4001)

        template = GlobalSkuTemplate.objects.filter(pk=template_id).first()
        if not template:
            return error('规格模板不存在', code=4042)

        if GlobalMenuSku.objects.filter(item=item, template=template).exists():
            return error('该商品已绑定此规格模板，无需重复绑定', code=4003)

        price_delta = request.data.get('price_delta')
        if price_delta is None:
            price_delta = template.default_price_delta

        data = {
            'item': item.id,
            'template': template.id,
            'price_delta': price_delta,
            'is_active': request.data.get('is_active', True),
            'sort_order': request.data.get('sort_order', 0),
            'ingredients': request.data.get('ingredients', [])
        }
        serializer = GlobalMenuSkuSerializer(data=data)
        if not serializer.is_valid():
            return error(str(serializer.errors), code=4001)

        sku = serializer.save()
        return ok(GlobalMenuSkuSerializer(sku).data, message='规格绑定成功')


class GlobalMenuSkuDetailView(APIView):
    """
    PUT    /api/admin/menus/global-skus/<int:pk>/ - 修改商品规格（加价、状态、定制配料）
    DELETE /api/admin/menus/global-skus/<int:pk>/ - 移除商品规格
    """
    permission_classes = [IsAdmin]

    def put(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可修改商品规格', code=4031)

        sku = GlobalMenuSku.objects.filter(pk=pk).first()
        if not sku:
            return error('商品规格不存在', code=4041)

        serializer = GlobalMenuSkuSerializer(sku, data=request.data, partial=True)
        if not serializer.is_valid():
            logger.warning(f"[AdminMenuSkuUpdate] 参数校验失败: id={pk}, errors={serializer.errors}")
            return error(str(serializer.errors), code=4001)

        updated_sku = serializer.save()
        logger.info(f"[AdminMenuSkuUpdate] 管理员 {request.user.username} 更新全局规格: id={pk}, name={updated_sku.name}")
        return ok(GlobalMenuSkuSerializer(updated_sku).data, message='商品规格更新成功')

    def delete(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可删除商品规格', code=4031)

        sku = GlobalMenuSku.objects.filter(pk=pk).first()
        if not sku:
            return error('商品规格不存在', code=4041)

        sku_name = sku.name
        sku.delete()
        logger.info(f"[AdminMenuSkuDelete] 管理员 {request.user.username} 删除全局规格: id={pk}, name={sku_name}")
        return ok(message='商品规格已移除')


class GlobalMenuSkuResetRecipeView(APIView):
    """
    POST /api/admin/menus/global-skus/<int:pk>/reset-recipe/ - 一键重置为模板默认配方
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        if not request.user.is_super_admin:
            return error('仅超级管理员可重置配方', code=4031)

        sku = GlobalMenuSku.objects.filter(pk=pk).first()
        if not sku:
            return error('商品规格不存在', code=4041)

        sku.ingredients.all().delete()
        updated_sku = GlobalMenuSku.objects.filter(pk=pk).select_related(
            'item', 'item__category', 'template'
        ).prefetch_related(
            'ingredients', 'ingredients__material', 'template__ingredients', 'template__ingredients__material'
        ).first()

        return ok(GlobalMenuSkuSerializer(updated_sku).data, message='已重置为规格模板默认配方')


class StoreMenuItemListView(APIView):
    """
    GET  /api/admin/menus/store-items/ - 获取门店菜单列表（含基础价格和上下架状态与关联规格）
    POST /api/admin/menus/store-items/sync/ - 手动触发门店菜单与全局型号同步
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        user = request.user
        store_id = request.query_params.get('store_id')

        qs = MenuItem.objects.all().select_related(
            'store', 'global_item', 'global_item__category', 'device_model'
        ).prefetch_related(
            'skus', 'skus__global_sku', 'skus__global_sku__template',
            'skus__global_sku__ingredients__material',
            'skus__global_sku__template__ingredients__material'
        ).order_by('sort_order', 'id')

        if not user.is_super_admin:
            allowed_stores = list(user.stores.values_list('id', flat=True))
            if store_id and int(store_id) in allowed_stores:
                qs = qs.filter(store_id=int(store_id))
            else:
                qs = qs.filter(store_id__in=allowed_stores)
        elif store_id:
            qs = qs.filter(store_id=store_id)

        # 确保每个本地商品都同步拥有对应的全局规格
        for item in qs:
            active_g_skus = item.global_item.skus.all()
            for g_sku in active_g_skus:
                if not MenuSku.objects.filter(item=item, global_sku=g_sku).exists():
                    MenuSku.objects.create(
                        item=item,
                        global_sku=g_sku,
                        price_delta=g_sku.price_delta,
                        is_active=g_sku.is_active,
                        sort_order=g_sku.sort_order
                    )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StoreMenuItemSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class StoreMenuItemDetailView(APIView):
    """
    PUT /api/admin/menus/store-items/<int:pk>/ - 门店管理员微调价格 (±20%) 或切换上下架
    """
    permission_classes = [IsAdmin]

    def put(self, request, pk):
        user = request.user
        item = MenuItem.objects.filter(pk=pk).select_related('store', 'global_item').first()
        if not item:
            return error('门店商品不存在', code=4041)

        if not user.is_super_admin and item.store not in user.stores.all():
            return error('无权修改该门店商品', code=4031)

        new_base_price = request.data.get('base_price')
        is_active = request.data.get('is_active')

        if is_active is not None:
            item.is_active = bool(is_active)

        if new_base_price is not None:
            new_base_price = int(new_base_price)
            # 校验 ±20% 范围
            global_p = item.global_item.base_price
            min_p = int(global_p * 0.8)
            max_p = int(global_p * 1.2)
            if new_base_price < min_p or new_base_price > max_p:
                return error(f'门店价格只能在全局价格 ({global_p/100:.2f}元) 的 ±20% 范围内调整（{min_p/100:.2f} ~ {max_p/100:.2f} 元）', code=4002)
            item.base_price = new_base_price

        item.save()
        return ok(StoreMenuItemSerializer(item).data, message='门店商品配置更新成功')


class StoreMenuSyncView(APIView):
    """
    POST /api/admin/menus/store-sync/<int:store_id>/ - 触发指定门店的全局商品同步
    """
    permission_classes = [IsAdmin]

    def post(self, request, store_id):
        store = Store.objects.filter(pk=store_id).first()
        if not store:
            return error('门店不存在', code=4041)

        if not request.user.is_super_admin and store not in request.user.stores.all():
            return error('无权操作该门店', code=4031)

        MenuItem.sync_store_menu(store)
        return ok(message=f'门店 {store.name} 菜单已成功同步最新全局商品')


class StoreMenuItemSkuListView(APIView):
    """
    GET /api/admin/menus/store-items/<int:item_id>/skus/
    获取指定门店商品的规格列表 (MenuSku)
    """
    permission_classes = [IsAdmin]

    def get(self, request, item_id):
        item = MenuItem.objects.filter(pk=item_id).first()
        if not item:
            return error('门店商品不存在', code=4041)

        # 校验或自动补齐 SKU
        for g_sku in item.global_item.skus.all():
            if not MenuSku.objects.filter(item=item, global_sku=g_sku).exists():
                MenuSku.objects.create(
                    item=item,
                    global_sku=g_sku,
                    price_delta=g_sku.price_delta,
                    is_active=g_sku.is_active,
                    sort_order=g_sku.sort_order
                )

        skus = MenuSku.objects.filter(item=item).select_related(
            'global_sku', 'global_sku__template', 'item', 'item__global_item'
        ).prefetch_related(
            'global_sku__ingredients__material',
            'global_sku__template__ingredients__material'
        ).order_by('sort_order', 'id')

        serializer = StoreMenuSkuSerializer(skus, many=True)
        return ok(serializer.data)


class StoreMenuSkuDetailView(APIView):
    """
    PUT /api/admin/menus/store-skus/<int:pk>/
    更新门店商品规格启用状态 (is_active) 或价格增量 (price_delta)
    业务规则：只能做减法，全局控制！
    """
    permission_classes = [IsAdmin]

    def put(self, request, pk):
        user = request.user
        menu_sku = MenuSku.objects.filter(pk=pk).select_related(
            'item', 'item__store', 'item__global_item', 'global_sku'
        ).first()
        if not menu_sku:
            return error('门店规格不存在', code=4041)

        if not user.is_super_admin and menu_sku.item.store not in user.stores.all():
            return error('无权修改该门店规格', code=4031)

        is_active = request.data.get('is_active')
        price_delta = request.data.get('price_delta')

        if is_active is not None:
            new_active = bool(is_active)
            if new_active:
                # 校验全局控制：如果全局规格已停用，则门店设备无法单独启用该规格！
                if not menu_sku.global_sku.is_active:
                    return error('该规格在全局已停用，门店设备无法单独开启（严格遵循“只能做减法，受全局控制”原则）', code=4003)
                if not menu_sku.item.global_item.is_active:
                    return error('该商品在全局已下架，无法单独开启规格', code=4003)
            menu_sku.is_active = new_active

        if price_delta is not None:
            price_delta = int(price_delta)
            global_final = menu_sku.item.global_item.base_price + menu_sku.global_sku.price_delta
            local_final = menu_sku.item.base_price + price_delta
            min_final = int(global_final * 0.8)
            max_final = int(global_final * 1.2)
            if local_final < min_final or local_final > max_final:
                return error(f'规格最终售价 ({local_final/100:.2f}元) 必须在全局最终售价 ({global_final/100:.2f}元) 的 ±20% 范围内（{min_final/100:.2f} ~ {max_final/100:.2f} 元）', code=4002)
            menu_sku.price_delta = price_delta

        menu_sku.save()
        logger.info(
            f"[AdminStoreSkuUpdate] 管理员 {user.username} 更新门店规格: id={pk}, "
            f"is_active={menu_sku.is_active}, price_delta={menu_sku.price_delta}"
        )
        return ok(StoreMenuSkuSerializer(menu_sku).data, message='门店规格配置更新成功')


