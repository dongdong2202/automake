"""
菜单服务层模块：饮品售罄状态计算
"""

import json
import logging
from decimal import Decimal
from django_redis import get_redis_connection

from stores.models import Store
from devices.models import Device, DeviceBarrelDict, DeviceMaterialStock
from menus.models import MenuItem
from global_config.models import GlobalMenuSku, GlobalSkuIngredient, GlobalSkuTemplateIngredient

from utils.redis_keys import get_stock_key

logger = logging.getLogger(__name__)


def get_redis_stock_key(device_sn: str, mat_code: str) -> str:
    """获取物料在 Redis 中的库存 key（已委托至 utils.redis_keys.get_stock_key）"""
    return get_stock_key(device_sn, mat_code)


def calculate_device_sold_out_items(device_sn: str, threshold: float = 500.0) -> dict:
    """
    计算并返回指定设备下已售罄的饮品菜单 ID 列表。

    核心判定规则：
    1. 料桶食材逻辑（Redis 实时驱动）：
       - 设备可能由多个料桶存放同一种物料（例如 b01 和 b02 均为 fresh_milk），聚合相加计算总余量；
       - 当某种食材物料的总余量 total_volume < threshold（默认 500.0 ml/g）时，该食材判定为缺料售罄；
    2. 杯型与耗材逻辑（MySQL 数据库驱动）：
       - 杯型与耗材（paperL, paperM, plasticL, plasticM, membrane, lid 等）通过 MySQL DeviceConsumableStock 查询剩余数量；
       - 当耗材剩余数量 quantity <= 0 时，判定该耗材缺料；
    3. 配方关联与规格分组：
       - 分析饮品（MenuItem）各规格组（default/主配方、杯型、温度等），若主配方或必选规格组全部选项均缺料，判定整品售罄。
    """
    device = None
    store = None

    # 1. 查询目标设备与所属门店
    device = Device.objects.select_related('store', 'device_model').filter(device_sn=str(device_sn)).first()
    if device:
        store = device.store
    else:
        # 兼容按 store_id 或 store.code 查询
        if str(device_sn).isdigit():
            store = Store.objects.filter(pk=int(device_sn)).first()
        if not store:
            store = Store.objects.filter(code=str(device_sn)).first()
        if store:
            device = store.devices.select_related('device_model').first()

    if not device or not store:
        return {
            'device_sn': str(device_sn),
            'sold_out_item_ids': [],
            'shortage_materials': []
        }

    actual_device_sn = device.device_sn
    redis_conn = get_redis_connection("default")

    # 2. 收集设备涉及的所有物料编码
    from inventory.models import Material
    from devices.models import DeviceConsumableStock

    barrel_mappings = DeviceBarrelDict.objects.filter(device=device).select_related('material')
    device_mat_codes = set()
    for bm in barrel_mappings:
        if bm.material:
            device_mat_codes.add(bm.material.code)

    for sc in DeviceMaterialStock.objects.filter(device=device):
        if sc.code:
            device_mat_codes.add(sc.code)

    # 区分食材类物料与杯型耗材类物料
    consumables_records = {cs.code_id: cs for cs in DeviceConsumableStock.objects.filter(device=device)}
    consumables_in_db = {cs.code_id: cs.quantity for cs in consumables_records.values()}
    
    # 获取所有已知物料的分类
    cup_and_consumable_codes = set(consumables_in_db.keys())
    cup_and_consumable_codes.update(['paperL', 'paperM', 'plasticL', 'plasticM', 'membrane', 'lid'])
    
    # 3. 筛选缺料物料集合
    shortage_materials = set()

    # 3.1 杯型与耗材：通过 MySQL 数据库校验 (当数量少于停售阈值或 <= 0 时为缺料停售)
    for cup_code in cup_and_consumable_codes:
        cs = consumables_records.get(cup_code)
        stop_level = getattr(cs, 'stop_sale_level', 5) if cs else 0
        qty = cs.quantity if cs else 0
        if qty < stop_level or qty <= 0:
            shortage_materials.add(cup_code)

    # 3.2 食材料桶：通过 Redis 实时余量校验 (多桶累计 < 500ml 判定为售罄缺料)
    aggregated_materials = {}

    # 读取 Redis 监控快照
    try:
        snapshot_json = redis_conn.get(f"automake:monitor:snapshot:{actual_device_sn}")
        if snapshot_json:
            if isinstance(snapshot_json, bytes):
                snapshot_json = snapshot_json.decode('utf-8')
            snap_data = json.loads(snapshot_json)
            for mat_code, mat_info in snap_data.get('materials', {}).items():
                if isinstance(mat_info, dict) and mat_code not in cup_and_consumable_codes:
                    vol = float(mat_info.get('total_volume', 0))
                    aggregated_materials[mat_code] = vol
    except Exception as e:
        logger.warning(f"[SoldOut] 读取 Redis 快照异常: {e}")

    # 读取 Redis 实时库存键
    for mat_code in device_mat_codes:
        if mat_code in cup_and_consumable_codes:
            continue
        stock_key = get_redis_stock_key(actual_device_sn, mat_code)
        val = redis_conn.get(stock_key)
        if val is not None:
            try:
                vol = float(val)
                aggregated_materials[mat_code] = vol
            except (ValueError, TypeError):
                pass

    for mat_code in device_mat_codes:
        if mat_code in cup_and_consumable_codes:
            continue
        total_vol = aggregated_materials.get(mat_code, 0.0)
        if total_vol < threshold:  # 累计少于 500ml 停止售卖
            shortage_materials.add(mat_code)

    if not device.device_model:
        return {
            'device_sn': actual_device_sn,
            'sold_out_item_ids': [],
            'shortage_materials': list(shortage_materials)
        }

    # 4. 获取当前门店及当前设备型号下所有有效 MenuItem (严格限定当前设备型号，杜绝跨型号借调)
    items_query = MenuItem.objects.filter(
        store=store,
        device_model=device.device_model,
        global_item__category__device_model=device.device_model,
        is_active=True
    )

    menu_items = (
        items_query
        .select_related('global_item')
        .prefetch_related('skus', 'skus__global_sku')
    )

    # 5. 分析每个 MenuItem 的配方用料
    sold_out_item_ids = []

    # 预加载所有涉及的 SKU 配料
    global_sku_ids = set()
    for m_item in menu_items:
        for s in m_item.skus.all():
            if s.is_active and s.global_sku_id:
                global_sku_ids.add(s.global_sku_id)

    sku_ingredients_map = {}
    if global_sku_ids:
        # 专属配料
        for ing in GlobalSkuIngredient.objects.filter(sku_id__in=global_sku_ids).select_related('material'):
            if ing.material and ing.material.code:
                sku_ingredients_map.setdefault(ing.sku_id, set()).add(ing.material.code)

        # 模板默认配料回退
        missing_skus = [gid for gid in global_sku_ids if gid not in sku_ingredients_map]
        if missing_skus:
            skus_with_tpl = GlobalMenuSku.objects.filter(id__in=missing_skus).select_related('template')
            tpl_to_skus = {}
            for s in skus_with_tpl:
                if s.template_id:
                    tpl_to_skus.setdefault(s.template_id, []).append(s.id)
            if tpl_to_skus:
                for t_ing in GlobalSkuTemplateIngredient.objects.filter(template_id__in=tpl_to_skus.keys()).select_related('material'):
                    if t_ing.material and t_ing.material.code:
                        for s_id in tpl_to_skus.get(t_ing.template_id, []):
                            sku_ingredients_map.setdefault(s_id, set()).add(t_ing.material.code)

    for m_item in menu_items:
        active_skus = [s for s in m_item.skus.all() if s.is_active]
        if not active_skus:
            # 没有可用规格，直接判定售罄
            sold_out_item_ids.append(m_item.id)
            continue

        # 按 SKU 规格属性分组 (例如: default/规格/杯型/温度/冰量/糖度)
        sku_groups = {}
        for sku in active_skus:
            group_key = 'default'
            if sku.global_sku and sku.global_sku.template:
                group_key = sku.global_sku.template.category or 'default'
            sku_groups.setdefault(group_key, []).append(sku)

        # 检查是否每个规格组均存在至少一个物料充足的可用选项
        # 只要有任何一个必选规格组（如主配方/杯型/默认规格）的所有选项均缺料，整杯饮品即无法制作，判定为售罄
        is_item_sold_out = False
        for group_name, skus_in_group in sku_groups.items():
            has_available_sku_in_group = False
            for sku in skus_in_group:
                needed_mats = sku_ingredients_map.get(sku.global_sku_id, set())
                # 检查该规格所需物料是否全部充足
                if not any(mat in shortage_materials for mat in needed_mats):
                    has_available_sku_in_group = True
                    break
            
            if not has_available_sku_in_group:
                # 该规格分组的所有选项均因缺料无法制作
                is_item_sold_out = True
                break

        if is_item_sold_out:
            sold_out_item_ids.append(m_item.id)

    return {
        'device_sn': actual_device_sn,
        'sold_out_item_ids': sold_out_item_ids,
        'shortage_materials': list(shortage_materials)
    }
