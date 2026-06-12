"""
菜单模块视图

仅提供获取指定门店完整菜单的只读接口。
菜单数据在运行时通过门店的 MenuItem 关联至全局的 GlobalMenuItem、GlobalMenuCategory 和 GlobalMenuSku 动态组装返回。
"""

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from utils.response import ok, error
from stores.models import Store
from .models import MenuItem


class StoreMenuView(APIView):
    """
    门店菜单接口

    GET /api/menu/store/{store_id}
    返回指定门店的完整菜单（分类 → 商品 → 规格/SKU）。
    前置依赖：门店必须存在且处于营业状态。
    所有分类、商品、SKU 关系都是在运行时基于全局配置和本地价格微调（ base_price ）动态拼装。
    """
    permission_classes = [AllowAny]  # 浏览菜单无需登录

    def get(self, request, store_id):
        # 检查门店是否存在且营业
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return error('门店不存在', code=3001, status=404)

        if not store.is_open:
            return error('门店暂未营业', code=3002, status=400)

        # 自动拉取/同步全局配置的最新菜单及规格
        MenuItem.sync_store_menu(store)

        # 获取当前门店所有上架的 MenuItem，并通过 select_related 预加载关联的全局信息
        local_items = (
            MenuItem.objects
            .filter(store=store, is_active=True)
            .select_related('global_item', 'global_item__category', 'device_type')
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
                    'attributes': local_sku.global_sku.attributes,
                    'price_delta': local_sku.price_delta,
                    'is_active': local_sku.is_active,
                    'sort_order': local_sku.sort_order
                })

            categories_dict[g_cat.id]['items_list'].append({
                'id': item.id,
                'name': g_item.name,
                'description': g_item.description,
                'image_url': g_item.image_url,
                'base_price': item.base_price,
                'is_active': item.is_active,
                'sort_order': item.sort_order,
                'skus': skus_list
            })

        # 按排序权重及 ID 排序
        sorted_categories = sorted(categories_dict.values(), key=lambda c: (c['sort_order'], c['id']))
        for cat in sorted_categories:
            cat['items'] = sorted(cat['items_list'], key=lambda i: (i['sort_order'], i['id']))
            del cat['items_list']

        return ok({
            'store_id': store.id,
            'store_name': store.name,
            'categories': sorted_categories,
        })
