"""
菜单模块视图

仅提供获取指定门店完整菜单的只读接口。
菜单数据在运行时通过门店的 MenuItem 关联至全局的 GlobalMenuItem、GlobalMenuCategory 和 GlobalMenuSku 动态组装返回。
"""

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter

from utils.response import ok, error
from stores.models import Store
from .models import MenuItem
from devices.models import Device

class StoreMenuView(APIView):
    """
    设备/门店菜单接口

    GET /api/menu/store/{device_sn}
    根据设备编号（或门店 ID/编码）获取该设备关联门店的完整菜单（分类 → 商品 → 规格/SKU）。
    前置依赖：设备与所属门店必须存在且处于营业状态。
    """
    permission_classes = [AllowAny]  # 浏览菜单无需登录

    @extend_schema(
        summary="获取设备菜单",
        description="根据设备序列号 device_sn（或兼容门店 ID）获取设备所属门店及对应型号的菜单配置（包含分类、商品、SKU 规格与价格）",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号（例如 DEV_100000、sn001 或门店 ID 100000）', required=True, type=str, location=OpenApiParameter.PATH)
        ]
    )
    def get(self, request, device_sn):
        device = None
        store = None

        # 1. 优先根据 device_sn 查找设备
        device = Device.objects.select_related('store', 'device_model').filter(device_sn=str(device_sn)).first()
        if device:
            store = device.store
            if not store:
                return error('该设备未绑定所属门店', code=3003, status=400)
        else:
            # 2. 兼容兜底：若传入的是纯数字 store_id 或 store.code
            if str(device_sn).isdigit():
                store = Store.objects.filter(pk=int(device_sn)).first()
            if not store:
                store = Store.objects.filter(code=str(device_sn)).first()

            if not store:
                return error('未找到对应的设备或门店', code=3001, status=404)
            # 获取该门店关联的首台设备
            device = store.devices.select_related('device_model').first()

        # 超级管理员 cxd 或 super_admin 可以查看任意门店菜单，且不受营业状态限制
        is_cxd = False
        if request.user and request.user.is_authenticated:
            if request.user.username == 'cxd' or request.user.is_superuser or getattr(request.user, 'role', None) == 'super_admin':
                is_cxd = True

        if not store.is_open and not is_cxd:
            return error('门店暂未营业', code=3002, status=400)

        # 获取该设备或门店所有上架的 MenuItem
        items_query = MenuItem.objects.filter(store=store, is_active=True)
        if device and device.device_model:
            # 如果该设备有关联的特定设备型号，且该型号在当前门店有上架商品，则优先按型号筛选
            matched_items = items_query.filter(device_model=device.device_model)
            if matched_items.exists():
                items_query = matched_items

        local_items = (
            items_query
            .select_related('global_item', 'global_item__category', 'device_model')
            .prefetch_related('skus', 'skus__global_sku')
            .order_by('sort_order', 'id')
        )
        
        categories_dict = {}
        for item in local_items:
            if not item.is_active:
                continue
            g_item = item.global_item
            if not g_item.is_active:
                continue
            g_cat = g_item.category
            if not g_cat.is_active:
                continue

            # 按全局分类进行归类分组
            if g_cat.id not in categories_dict:
                icon_url = ''
                if g_cat.icon_url:
                    try:
                        icon_url = g_cat.icon_url.url
                    except Exception:
                        icon_url = str(g_cat.icon_url)
                categories_dict[g_cat.id] = {
                    'id': g_cat.id,
                    'name': g_cat.name,
                    'icon_url': icon_url,
                    'sort_order': g_cat.sort_order,
                    'items_list': []
                }

            # 获取并组装规格 (SKU)
            skus_list = []
            local_skus = sorted(item.skus.all(), key=lambda s: (s.sort_order, s.id))
            for local_sku in local_skus:
                if not local_sku.is_active:
                    continue
                if not local_sku.global_sku.is_active:
                    continue
                skus_list.append({
                    'id': local_sku.id,
                    'name': local_sku.global_sku.name,
                    'category': local_sku.global_sku.category,
                    'price_delta': local_sku.price_delta,
                    'is_active': local_sku.is_active,
                    'sort_order': local_sku.sort_order
                })

            def _get_media_path(val):
                if not val:
                    return ''
                return val.url if hasattr(val, 'url') else str(val).strip()

            categories_dict[g_cat.id]['items_list'].append({
                'id': item.id,
                'name': g_item.name,
                'description': g_item.price_description or g_item.description or '',
                'image_url': _get_media_path(g_item.image_url),
                'main_ingredients': g_item.main_ingredients or '',
                'price_description': g_item.price_description or g_item.description or '',
                'detail_page': _get_media_path(g_item.detail_page),
                'base_price': item.base_price,
                'global_base_price': g_item.base_price,
                'is_active': item.is_active,
                'sort_order': item.sort_order,
                'skus': skus_list
            })

        # 按排序权重及 ID 排序
        from .services import calculate_device_sold_out_items
        sold_out_info = calculate_device_sold_out_items(device.device_sn if device else str(device_sn))
        sold_out_set = set(sold_out_info.get('sold_out_item_ids', []))

        sorted_categories = sorted(categories_dict.values(), key=lambda c: (c['sort_order'], c['id']))
        for cat in sorted_categories:
            items_list = sorted(cat['items_list'], key=lambda i: (i['sort_order'], i['id']))
            for itm in items_list:
                itm['is_sold_out'] = itm['id'] in sold_out_set
            cat['items'] = items_list
            del cat['items_list']
            
        return ok({
            'device_sn': device.device_sn if device else str(device_sn),
            'device_name': device.device_name if device else '',
            'store_id': store.id,
            'store_name': store.name,
            'is_in_business_hours': store.is_in_business_hours,
            'sold_out_item_ids': list(sold_out_set),
            'categories': sorted_categories,
        })


class DeviceSoldOutItemsView(APIView):
    """
    饮品售罄查询接口
    
    GET /api/menu/sold-out/{device_sn}
    GET /api/menu/sold_out?device_sn=xxx
    
    当设备某个物料总量少于 10（可能多个桶装同种物料）时，
    返回设备编号以及受影响已售罄的菜单 ID 列表。
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="查询设备已售罄饮品菜单ID列表",
        description="根据设备编号查询当前物料总量少于10时已售罄的菜单商品ID列表（支持多料桶聚合）",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=False, type=str)
        ]
    )
    def get(self, request, device_sn=None):
        target_device_sn = device_sn or request.query_params.get('device_sn') or request.query_params.get('device') or request.query_params.get('store_id')
        if not target_device_sn:
            return error('缺少 device_sn 参数', code=400)

        from .services import calculate_device_sold_out_items
        sold_out_data = calculate_device_sold_out_items(target_device_sn)
        return ok(sold_out_data)


class DeviceMenuCategoriesQueryView(APIView):
    """
    设备菜单分类查询接口
    输入设备编号，获取该设备的菜单分类信息
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="设备菜单分类查询",
        description="输入设备编号，获取该设备的菜单分类信息（包括分类名称、标签和菜单商品ID列表）",
        parameters=[
            OpenApiParameter(name='device_sn', description='设备序列号', required=True, type=str)
        ]
    )
    def get(self, request):
        device_sn = request.query_params.get('device_sn')
        if not device_sn:
            return error('缺少 device_sn 参数', code=400)

        try:
            device = Device.objects.get(device_sn=device_sn)
        except Device.DoesNotExist:
            return error('设备不存在', code=404)

        if not device.store or not device.device_model:
            return ok([], message='查询成功')

        # 获取当前设备关联门店及设备型号下所有上架的 MenuItem
        items = (
            MenuItem.objects
            .filter(
                store=device.store,
                device_model=device.device_model,
                is_active=True,
                global_item__is_active=True,
                global_item__category__is_active=True
            )
            .select_related('global_item', 'global_item__category')
            .order_by('global_item__category__sort_order', 'global_item__category__id', 'sort_order', 'id')
        )

        categories_dict = {}
        for item in items:
            g_cat = item.global_item.category
            if g_cat.id not in categories_dict:
                categories_dict[g_cat.id] = {
                    "type": g_cat.label,
                    "label": g_cat.name,
                    "merchandises": []
                }
            categories_dict[g_cat.id]["merchandises"].append(str(item.id))

        # 按照分类本身的排序权重排序返回列表
        return ok(list(categories_dict.values()), message='查询成功')

