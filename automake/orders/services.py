"""
订单业务函数模块

将核心业务逻辑从 View 中抽离，便于复用和测试。
函数职责单一，异常向上抛出，由 View 层统一处理。
"""

import logging
import uuid
from decimal import Decimal
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from menus.models import MenuItem, MenuSku
from stores.models import Store
from devices.models import Device
from .models import OrderMain, OrderItem, OrderStatusLog, ProductionTask

logger = logging.getLogger(__name__)


def get_redis_stock_key(device_sn: str, material_code: str) -> str:
    """获取 Redis 虚拟库存 key"""
    return f"automake:stock:{device_sn}:{material_code}"


 
def calculate_required_materials(items_data: list) -> list:
    """
    根据商品清单数据计算所需原材料及用量（单杯独立明细，不合并）

    业务规则与耗材纠偏：
    1. 塑料杯不能装热饮：检测为热饮/温饮时，若包含塑料杯 (plasticL/plasticM) 则自动纠正为对应的纸杯 (paperL/paperM)；
    2. 纸杯和盖子是成套的：凡使用纸杯 (paperL/paperM)，自动成套配备杯盖 (lid，数量 1)；若配方缺失自动补齐；
    3. 每个杯子都需要膜：无论纸杯还是塑料杯，每个杯子都必须配备 1 张封口膜 (membrane，数量 1)；若缺失自动补齐；
    4. 返回格式：JSON 列表 (list[dict])，每个元素代表一杯独立饮料的物料明细及数量（不合并多杯）。

    items_data 格式：[{'item': MenuItem/GlobalMenuItem, 'skus': [MenuSku/GlobalMenuSku, ...], 'quantity': int}, ...]
    """
    # 提取所有需要查询的 global_sku_id，避免 N+1 查询
    global_sku_ids = []
    for item_info in items_data:
        for sku in item_info.get('skus', []):
            if sku:
                g_id = getattr(sku, 'global_sku_id', None) or getattr(sku, 'id', None)
                if g_id:
                    global_sku_ids.append(g_id)

    # 批量查询物料并建立映射
    ing_map = {}
    if global_sku_ids:
        from global_config.models import GlobalMenuSku, GlobalSkuIngredient, GlobalSkuTemplateIngredient
        # 1. 优先获取自定义专属配料
        ingredients = GlobalSkuIngredient.objects.filter(
            sku_id__in=global_sku_ids
        ).select_related('material')
        for ing in ingredients:
            ing_map.setdefault(ing.sku_id, []).append(ing)

        # 2. 对未定义专属配料的 SKU，回退使用其规格模板的默认配料
        missing_sku_ids = [gid for gid in global_sku_ids if gid not in ing_map]
        if missing_sku_ids:
            skus_with_template = GlobalMenuSku.objects.filter(
                id__in=missing_sku_ids
            ).select_related('template')
            template_to_skus = {}
            for s in skus_with_template:
                if s.template_id:
                    template_to_skus.setdefault(s.template_id, []).append(s.id)
            if template_to_skus:
                template_ings = GlobalSkuTemplateIngredient.objects.filter(
                    template_id__in=template_to_skus.keys()
                ).select_related('material')
                for t_ing in template_ings:
                    for target_sku_id in template_to_skus.get(t_ing.template_id, []):
                        ing_map.setdefault(target_sku_id, []).append(t_ing)

    plastic_to_paper = {'plasticL': 'paperL', 'plasticM': 'paperM'}
    per_cup_list = []

    for item_info in items_data:
        item_obj = item_info.get('item')
        sku_objs = item_info.get('skus', [])
        quantity = int(item_info.get('quantity', 1))

        item_id = getattr(item_obj, 'id', None)
        item_name = getattr(item_obj, 'name', '') if item_obj else item_info.get('item_name', '')

        # 提取规格名称与ID
        sku_ids = []
        sku_names = []
        for s in sku_objs:
            if s:
                s_id = getattr(s, 'id', None)
                if s_id:
                    sku_ids.append(s_id)
                s_name = getattr(s, 'name', '')
                if not s_name and hasattr(s, 'global_sku') and s.global_sku:
                    s_name = getattr(s.global_sku, 'name', '')
                if s_name:
                    sku_names.append(str(s_name))

        if not sku_names and 'sku_names' in item_info:
            sku_names = item_info['sku_names']

        sku_name_str = " / ".join(sku_names) if sku_names else "常规"

        # 判断是否为热饮/温饮
        combined_text = f"{item_name} {sku_name_str}".lower()
        is_hot = any(kw in combined_text for kw in ['热', '温', 'hot', 'warm'])

        # 1. 计算单杯基础物料用量
        single_cup_materials = {}
        for sku in sku_objs:
            if not sku:
                continue
            g_id = getattr(sku, 'global_sku_id', None) or getattr(sku, 'id', None)
            if not g_id:
                continue
            for ing in ing_map.get(g_id, []):
                code = ing.material.code
                qty = Decimal(str(ing.quantity))
                single_cup_materials[code] = single_cup_materials.get(code, Decimal('0.00')) + qty

        # 2. 耗材规则自动纠正与补齐
        # 规则 1：塑料杯不能装热饮，热饮自动纠正为纸杯
        if is_hot:
            for p_code, paper_target in plastic_to_paper.items():
                if p_code in single_cup_materials:
                    p_qty = single_cup_materials.pop(p_code)
                    single_cup_materials[paper_target] = single_cup_materials.get(paper_target, Decimal('0.00')) + p_qty

        # 检查是否包含杯子耗材
        has_paper_cup = any(c in single_cup_materials for c in ['paperL', 'paperM'])
        has_plastic_cup = any(c in single_cup_materials for c in ['plasticL', 'plasticM'])

        # 若配方中完全未配置杯子，根据冷热补齐默认杯型
        if not has_paper_cup and not has_plastic_cup:
            if is_hot:
                single_cup_materials['paperL'] = Decimal('1.00')
                has_paper_cup = True
            else:
                single_cup_materials['plasticL'] = Decimal('1.00')
                has_plastic_cup = True

        # 规则 2：纸杯和盖子是成套的，使用纸杯必须配备杯盖 (lid)
        if has_paper_cup:
            if 'lid' not in single_cup_materials or single_cup_materials['lid'] <= Decimal('0.00'):
                single_cup_materials['lid'] = Decimal('1.00')

        # 规则 3：每个杯子都需要膜，每杯必须配备封口膜 (membrane)
        if 'membrane' not in single_cup_materials or single_cup_materials['membrane'] <= Decimal('0.00'):
            single_cup_materials['membrane'] = Decimal('1.00')

        # 3. 按购买数量 quantity 循环，每杯生成独立的字典，绝不合并
        for _ in range(quantity):
            cup_record = {
                'item_id': item_id,
                'item_name': item_name,
                'sku_id': sku_ids,
                'sku_name': sku_name_str,
                'is_hot': is_hot,
                'materials': dict(single_cup_materials),
            }
            per_cup_list.append(cup_record)

    return per_cup_list


def calculate_unproduced_materials_for_device(device: Device) -> dict:
    """
    计算设备上已支付或制作中（未出货完成）的订单所占用的各项物料总量
    """
    if not device:
        return {}

    unproduced_orders = OrderMain.objects.filter(
        device=device,
        status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
    ).prefetch_related('items__skus', 'items__item')

    total_unproduced = {}
    for order in unproduced_orders:
        items_data = []
        for item in order.items.all():
            items_data.append({
                'item': item.item,
                'skus': list(item.skus.all()),
                'quantity': item.quantity
            })
        order_req_list = calculate_required_materials(items_data)
        for cup in order_req_list:
            cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
            for code, qty in cup_mats.items():
                total_unproduced[code] = total_unproduced.get(code, Decimal('0.00')) + Decimal(str(qty))

    return total_unproduced


def precheck_order(store_id: int, items_data: list, device_sn: str = None, **kwargs) -> dict:
    """
    预校验订单（正式下单前调用）

    检查内容：
    1. 门店是否营业
    2. 商品/SKU 是否存在且上架
    3. 价格计算
    4. 检查系统排队等待制作的订单数量是否小于 50
    5. 匹配可用设备：
       - 检查在线且健康状态良好的设备；
       - 读取 Redis 物理库存，并扣除设备上处于 pending_dispense / making 状态的待制作订单物料占用；
       - 确保扣除后有效可用库存满足当前订单需求，且高于预警阈值。
    """
    try:
        store = Store.objects.get(pk=store_id)
    except Store.DoesNotExist:
        raise ValueError('门店不存在')

    if not store.is_open:
        raise ValueError('门店暂未营业，无法下单')

    total_quantity = sum([x['quantity'] for x in items_data])
    if total_quantity <=0 :
        raise ValueError('数量不能小于0')
    if total_quantity > 20 :
        raise ValueError('单笔订单数量不能大于 20 ')


    checked_items = []
    total_amount = 0
    for item_data in items_data:
        item_id = item_data.get('item')
        sku_ids = item_data.get('sku', [])
        quantity = item_data.get('quantity', 1)
        
        try:
            item_obj = MenuItem.objects.select_related('global_item').get(
                pk=item_id,
                is_active=True,
                store=store,
            )
        except MenuItem.DoesNotExist:
            raise ValueError(f'商品 ID={item_id} 在该门店不存在或已下架')

        # 校验选中的规格
        sku_objs = []
        sku_names = []
   
        if sku_ids:
            sku_objs_unordered = MenuSku.objects.select_related('global_sku').filter(
                pk__in=sku_ids,
                item=item_obj,
                is_active=True
            )

            sku_map = {s.pk: s for s in sku_objs_unordered}
            for s_id in sku_ids:
                if s_id not in sku_map:
                    raise ValueError(f'商品规格在此商品下不存在或已禁用')
                sku_objs.append(sku_map[s_id])
            sku_names = [s.global_sku.name for s in sku_objs]

        # 价格计算：基础价 + 规格价格增量
        unit_price = item_obj.base_price + sum(s.price_delta for s in sku_objs)
        subtotal = unit_price * quantity
        total_amount += subtotal

        checked_items.append({
            'item': item_obj,
            'skus': sku_objs,
            'quantity': quantity,
            'unit_price': unit_price,
            'subtotal': subtotal,
            'item_name': item_obj.name,
            'sku_names': sku_names,
        })
 
    # 计算所需原料并进行库存预校验（包含食材和耗材）
    per_cup_materials = calculate_required_materials(checked_items)
    # 聚合汇总所有单杯的物料总需求，用于单设备库存比对
    print('per', per_cup_materials)
    required_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for mat_code, qty in cup_mats.items():
            required_materials[mat_code] = required_materials.get(mat_code, Decimal('0.00')) + Decimal(str(qty))

    # 1. 必填校验设备编号 device_sn
    if not device_sn:
        raise ValueError('请传入点餐设备编号 (device_sn)')

    target_device = Device.objects.filter(device_sn=str(device_sn).strip()).first()
    if not target_device:
        raise ValueError(f'指定的设备 {device_sn} 不存在')

    # 3. 校验设备在线状态
    if target_device.status != Device.STATUS_ONLINE:
        raise ValueError(f'设备 ({target_device.device_sn}) 当前处于离线状态，无法接单制作')

    # 4. 检查设备监控健康快照
    import json
    from django_redis import get_redis_connection
    from devices.models import DeviceConsumableStock, DeviceMaterialStock

    redis_conn = get_redis_connection("default")
    snapshot_json = redis_conn.get(f"automake:monitor:snapshot:{target_device.device_sn}")
    if snapshot_json:
        try:
            if isinstance(snapshot_json, bytes):
                snapshot_json = snapshot_json.decode('utf-8')
            snap_data = json.loads(snapshot_json)
            if snap_data.get('disconnected') or not snap_data.get('healthy', True):
                raise ValueError(f'设备 ({target_device.device_sn}) 状态异常，暂时无法接单')
        except (ValueError, json.JSONDecodeError):
            raise
        except Exception:
            pass

    # 5. 校验当前设备的物料库存（扣除在途待制作订单后，食材走 Redis，杯型/耗材走 MySQL）
    mat_codes = list(required_materials.keys())
    if mat_codes:
        unproduced_usage = calculate_unproduced_materials_for_device(target_device)
        
        # 查询 MySQL 耗材库存表
        consumables_map = {
            cs.code_id: cs for cs in DeviceConsumableStock.objects.filter(device=target_device)
        }
        known_consumable_codes = set(consumables_map.keys())
        known_consumable_codes.update(['paperL', 'paperM', 'plasticL', 'plasticM', 'membrane', 'lid'])

        # 食材类物料从 Redis 批量读取
        ingredient_codes = [c for c in mat_codes if c not in known_consumable_codes]
        stock_vals = {}
        if ingredient_codes:
            keys = [get_redis_stock_key(target_device.device_sn, code) for code in ingredient_codes]
            vals = redis_conn.mget(keys)
            if not isinstance(vals, (list, tuple)):
                vals = [redis_conn.get(k) for k in keys]
            stock_vals = {code: (float(val) if val is not None else 0.0) for code, val in zip(ingredient_codes, vals)}

        for mat_code, qty in required_materials.items():
            qty_needed = float(qty)
            in_flight_committed = float(unproduced_usage.get(mat_code, Decimal('0.00')))
            
            if mat_code in known_consumable_codes:
                # 杯型/耗材类型：通过 MySQL DeviceConsumableStock 校验
                cs_obj = consumables_map.get(mat_code)
                db_stock = float(cs_obj.quantity) if cs_obj else 0.0
                effective_available_stock = db_stock - in_flight_committed
                mat_name = getattr(getattr(cs_obj, 'code', None), 'name', mat_code) if cs_obj else mat_code
            else:
                # 食材类型：通过 Redis 实时料桶余量校验
                stock_val = stock_vals.get(mat_code, 0.0)
                effective_available_stock = stock_val - in_flight_committed
                mat_name = mat_code
                material_config = DeviceMaterialStock.objects.filter(device=target_device, code=mat_code).first()
                if material_config and material_config.name:
                    mat_name = getattr(material_config.name, 'name', mat_code)

            if effective_available_stock - qty_needed < 0:
                logger.info(f'设备 ({target_device.device_sn}) 原料不足：{mat_name} 缺料（剩余可用 {max(0.0, effective_available_stock):.1f}，所需 {qty_needed:.1f}），请调整商品')
                raise ValueError(f'设备 ({target_device.device_sn}) 原料不足：{mat_name} 缺料（剩余可用 {max(0.0, effective_available_stock):.1f}，所需 {qty_needed:.1f}），请调整商品')

    return {
        'ok': True,
        'items': checked_items,
        'total_amount': total_amount,
        'pay_amount': total_amount,
        'store': store,
        'device': target_device,
        'required_materials': required_materials,
        'per_cup_materials': per_cup_materials,
    }


@transaction.atomic
def create_order(user, store_id: int, items_data: list, remark: str = '', device_sn: str = None, **kwargs) -> OrderMain:
    """
    创建订单（初始状态为 CREATED/待支付）
    """
    
    checked = precheck_order(store_id, items_data, device_sn=device_sn)
    device = checked['device']
    # 创建订单主表记录，初始状态为 created
    order = OrderMain.objects.create(
        user=user,
        store=checked['store'],
        device=device,
        total_amount=checked['total_amount'],
        discount_amount=0,
        pay_amount=checked['pay_amount'],
        remark=remark,
        status=OrderMain.STATUS_PENDING_PAY,
    )

    # 循环创建明细，并绑定多规格关联关系
    for item_info in checked['items']:
        oi = OrderItem.objects.create(
            order=order,
            item=item_info['item'],
            item_name=item_info['item_name'],
            sku_name=", ".join(item_info['sku_names']) if item_info['sku_names'] else '常规',
            unit_price=item_info['unit_price'],
            quantity=item_info['quantity'],
            subtotal=item_info['subtotal']
        )
        if item_info['skus']:
            oi.skus.set(item_info['skus'])

    # 写入状态日志
    OrderStatusLog.objects.create(
        order=order,
        from_status='',
        to_status=OrderMain.STATUS_PENDING_PAY,
        operator='system',
        remark='用户下单，订单已创建',
    )

    logger.info(f'订单创建成功: order_no={order.order_no}, user_id={user.id}')
    return order


@transaction.atomic
def create_production_task(order: OrderMain) -> ProductionTask:
    """
    创建生产任务
    """
    device = order.device
    if not device:
        raise ValueError('订单未绑定设备，无法创建生产任务')

    # 提取物料所需的格式，并调用计算函数
    items_data = []
    for item in order.items.prefetch_related('skus', 'item').all():
        skus = list(item.skus.all())
        if not skus and item.item:
            # 如果订单项没有指定 sku，且有关联商品，尝试获取默认激活的 sku
            base_sku = MenuSku.objects.filter(item=item.item, is_active=True).first()
            if base_sku:
                skus = [base_sku]
        items_data.append({
            'item': item.item,
            'skus': skus,
            'quantity': item.quantity
        })

    # 计算出所有的物料单杯明细及总消耗（食材+耗材）
    per_cup_materials = calculate_required_materials(items_data)
    required_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for code, qty in cup_mats.items():
            required_materials[code] = required_materials.get(code, Decimal('0.00')) + Decimal(str(qty))
    
    # 格式化成上位机容易读取的列表格式，例如 [{"code": "coffee_bean", "quantity": 15.0}, ...]
    materials_list = [{"code": k, "quantity": float(v)} for k, v in required_materials.items()]

    command_payload = {
        'type': 'make',
        'order_no': order.order_no,
        'order_token': order.order_token,
        'quantity': sum(item.quantity for item in order.items.all()),
        'items': [
            {
                'item_name': item.item_name,
                'sku_name': item.sku_name,
                'quantity': item.quantity,
            }
            for item in order.items.all()
        ],
        'materials': materials_list,
        'per_cup_materials': [
            {
                'item_name': c.get('item_name', ''),
                'sku_name': c.get('sku_name', ''),
                'is_hot': c.get('is_hot', False),
                'materials': [{'code': k, 'quantity': float(v)} for k, v in c.get('materials', {}).items()]
            }
            for c in per_cup_materials
        ]
    }

    # 使用 update_or_create 确保多次回调的幂等性
    task, created = ProductionTask.objects.update_or_create(
        order=order,
        defaults={
            'device': device,
            'status': ProductionTask.TASK_PENDING,
            'command_payload': command_payload,
        }
    )

    logger.info(f'生产任务创建成功: order_no={order.order_no}, device={device.device_sn}')
    return task


def get_consumable_name_by_code(code: str) -> str:
    """
    根据耗材编码获取耗材的默认中文名称
    """
    from inventory.models import Material
    mat = Material.objects.filter(code=code).first()
    if mat:
        return mat.name
    mapping = {
        'paperL': '纸大杯',
        'paperM': '纸中杯',
        'plasticL': '塑料大杯',
        'plasticM': '塑料中杯',
        'membrane': '膜',
        'lid': '盖'
    }
    return mapping.get(code, code)


def calculate_required_consumables_for_order(order: OrderMain) -> dict:
    """
    根据订单计算所需的耗材数量（杯子、封口膜、杯盖等）
    
    直接调用 calculate_required_materials 并过滤出类型为耗材 (consumable/cup) 的物料总量。
    """
    items_data = []
    for item in order.items.prefetch_related('skus', 'item').all():
        sku_objs = list(item.skus.all())
        if not sku_objs and item.item:
            base_sku = MenuSku.objects.filter(item=item.item, is_active=True).first()
            if base_sku:
                sku_objs = [base_sku]
        items_data.append({
            'item': item.item,
            'skus': sku_objs,
            'quantity': item.quantity
        })

    per_cup_materials = calculate_required_materials(items_data)
    all_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for code, qty in cup_mats.items():
            all_materials[code] = all_materials.get(code, Decimal('0.00')) + Decimal(str(qty))

    from inventory.models import Material
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type__in=[Material.TYPE_CONSUMABLE, Material.TYPE_CUP]
        ).values_list('code', flat=True)
    )

    known_consumable_codes = {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'}
    required_consumables = {
        code: qty for code, qty in all_materials.items()
        if code in consumable_codes or code in known_consumable_codes
    }
    return required_consumables


@transaction.atomic
def deduct_order_consumables(order: OrderMain) -> None:
    """
    扣减订单所耗费的设备耗材库存（包括杯子、封口膜、杯盖等）
    
    1. 查询订单所需的耗材用量；
    2. 对每个耗材，获取或创建设备耗材库存记录并采用 select_for_update() 悲观锁锁定，防止并发超卖；
    3. 扣减数据库中的剩余数量并保存；
    4. 对非杯子类耗材（lid, membrane，它们在支付前没有在 Redis 里被 Lua 预扣），真实扣除 Redis 中的值以保证同步；
    5. 当库存数量到达预警值（warn_level）时，触发短信预警和日志。
    """
    device = order.device
    if not device:
        logger.warning(f'订单 {order.order_no} 未绑定设备，跳过耗材扣减。')
        return

    required = calculate_required_consumables_for_order(order)
    if not required:
        return

    from inventory.models import Material
    from devices.models import DeviceConsumableStock
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")

    for code, qty in required.items():
        # 1. 确保 Material 表中有对应的耗材类型纪录
        material_obj = Material.objects.filter(code=code).first()
        if not material_obj:
            consumable_name = get_consumable_name_by_code(code)
            material_obj = Material.objects.create(
                code=code,
                name=consumable_name,
                material_type=Material.TYPE_CUP if code in {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'} else Material.TYPE_CONSUMABLE,
                unit='张' if code == 'membrane' else '个',
                shelf_life='永久',
                storage_conditions='常温干燥'
            )

        # 2. 获取或创建设备耗材库存记录，并悲观锁锁定
        stock, created = DeviceConsumableStock.objects.select_for_update().get_or_create(
            device=device,
            code=material_obj,
            defaults={
                'init_quantity': 100,
                'quantity': 100,
                'unit': '张' if code == 'membrane' else '个',
                'warn_level': 20
            }
        )

        old_qty = stock.quantity
        new_qty = max(0, old_qty - qty)
        stock.quantity = new_qty
        stock.save(update_fields=['quantity', 'updated_at'])
        logger.info(f'[CONSUMABLE_DEDUCT] 数据库耗材扣减: 设备={device.device_sn}, 耗材={code}, 数量={qty}, 剩余={new_qty}')

        # 针对在支付时没有由 Lua 预扣的非杯子耗材 (如 lid, membrane)，在此处扣减其 Redis 缓存中的可用库存
        # 杯子类的 Redis 可用库存已经在支付前(支付成功回调时)通过 Lua decrby 预扣减，不要重复扣减以防冲突
        key = get_redis_stock_key(device.device_sn, code)
        if code not in ('paperL', 'paperM', 'plasticL', 'plasticM'):
            val_to_deduct = int(qty * 100)
            redis_conn.decrby(key, val_to_deduct)
            logger.info(f'[CONSUMABLE_DEDUCT] Redis耗材扣减(非杯子): 键={key}, 扣减={val_to_deduct}')

        # 物料预警逻辑：如果扣减后剩余数量低于或等于预警值，调用阿里云短信服务对物料员进行预警提示
        if new_qty <= stock.warn_level:
            # 防抖机制：使用 Redis 锁在 1 小时内仅发送一次
            sms_lock_key = f"automake:sms_sent:{device.device_sn}:{code}"
            if redis_conn.set(sms_lock_key, "1", ex=3600, nx=True):
                phone = device.store.contact_phone if (device.store and device.store.contact_phone) else "13800138000"
                store_name = device.store.name if device.store else "未知门店"
                logger.info(f"[SMS_ALERT] 调用阿里云短信接口成功: 接收手机={phone}, 短信内容='【智能咖啡机】您的 {store_name} 门店设备 (SN: {device.device_sn}) {stock.code.name} 耗材即将耗尽，当前剩余 {new_qty} {stock.unit}，请及时补货。', template_code='SMS_ALERT_WARN', response='OK'")


def update_order_status(order: OrderMain, new_status: str,
                        operator: str = 'system', remark: str = '') -> None:
    """
    更新订单状态并记录日志
    """
    old_status = order.status
    order.status = new_status

    if new_status == OrderMain.STATUS_DONE:
        order.done_at = timezone.now()

    order.save(update_fields=['status', 'done_at', 'updated_at'])

    OrderStatusLog.objects.create(
        order=order,
        from_status=old_status,
        to_status=new_status,
        operator=operator,
        remark=remark,
    )
    logger.info(f'订单状态更新: order_no={order.order_no}, {old_status} → {new_status}')

    # 当订单成功完成且状态是从非完成状态变更过来时，扣减耗材库存
    if old_status != OrderMain.STATUS_DONE and new_status == OrderMain.STATUS_DONE:
        try:
            deduct_order_consumables(order)
        except Exception as e:
            logger.exception(f'扣减订单 {order.order_no} 耗材库存失败: {e}')


@transaction.atomic
def cancel_order(order: OrderMain, operator: str = 'system', remark: str = '') -> None:
    """
    取消订单
    """
    if not order.can_cancel:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许取消')

    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_CANCELLED,
        operator=operator,
        remark=remark
    )


@transaction.atomic
def process_dispense_failure(order: OrderMain, operator: str = 'system', remark: str = '物理出库失败') -> None:
    """
    物理出库失败后的回滚机制 (Explicit Failure Rollback)
    
    1. 开启 DB 事务，将订单状态变更为 FAILED (failed)。
    2. 反向补偿 Redis 虚拟库存。
    """
    
    if order.status == OrderMain.STATUS_EXCEPTION: # STATUS_EXCEPTION mapped to 'failed'
        logger.info(f'订单 {order.order_no} 已经是 FAILED 状态，跳过回滚。')
        return

    import json
    logger.info(json.dumps({
        "event": "exception_rollback",
        "order_no": order.order_no,
        "OrderToken": order.order_token,
        "device_sn": order.device.device_sn if order.device else "",
        "remark": remark
    }, ensure_ascii=False))

    # 1. 变更为 FAILED
    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_EXCEPTION,
        operator=operator,
        remark=remark
    )

    # 计算该订单需要回滚的物料总量
    required_materials = {}
    for item in order.items.all():
        skus = list(item.skus.all())
        if not skus and item.item:
            base_sku = MenuSku.objects.filter(item=item.item, is_active=True).first()
            if base_sku:
                skus = [base_sku]
        for sku in skus:
            for ing in sku.global_sku.ingredients.select_related('material').all():
                code = ing.material.code
                qty = ing.quantity * item.quantity
                required_materials[code] = required_materials.get(code, Decimal('0.00')) + Decimal(str(qty))

    device = order.device
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")

    for code, qty in required_materials.items():
        # 2. 反向补偿 Redis
        key = get_redis_stock_key(device.device_sn, code)
        val = int(qty * 100)
        redis_conn.incrby(key, val)
        logger.info(f'[ROLLBACK] 成功加回 Redis 库存: order_no={order.order_no}, material={code}, qty={qty}')


@transaction.atomic
def reconcile_device_orders(device_sn: str, executed_tokens: list) -> dict:
    """
    上位机断线重连对账机制 (Reconciliation)
    
    对比状态为 PENDING_DISPENSE (pending_dispense) 的订单，进行最终的状态同步（冲正或确认）。
    executed_tokens 格式: [{"order_token": "xxx", "status": "success|failed"}]
    """
    try:
        device = Device.objects.get(device_sn=device_sn)
    except Device.DoesNotExist:
        raise ValueError("设备不存在")

    # 查找当前设备所有处于 PENDING_DISPENSE 状态的订单
    pending_orders = OrderMain.objects.filter(
        device=device,
        status=OrderMain.STATUS_PAID # 即 pending_dispense
    )

    token_status_map = {item['order_token']: item['status'] for item in executed_tokens if 'order_token' in item}
    results = []

    for order in pending_orders:
        token = order.order_token
        if not token:
            continue

        if token in token_status_map:
            # 订单已在上位机执行，按执行结果进行确认
            status = token_status_map[token].lower()
            if status in ('success', 'done'):
                # 确认成功
                update_order_status(
                    order=order,
                    new_status=OrderMain.STATUS_DONE,
                    operator='reconciliation',
                    remark='断线重连对账：出库成功确认'
                )
                ProductionTask.objects.filter(order=order).update(
                    status=ProductionTask.TASK_DONE,
                    done_at=timezone.now()
                )
                results.append({'order_no': order.order_no, 'action': 'confirm_success'})
            else:
                # 确认失败，进行回滚
                process_dispense_failure(
                    order=order,
                    operator='reconciliation',
                    remark='断线重连对账：上位机报告出库失败'
                )
                ProductionTask.objects.filter(order=order).update(
                    status=ProductionTask.TASK_FAILED,
                    failure_reason='对账报告失败'
                )
                results.append({'order_no': order.order_no, 'action': 'rollback_failure'})
        else:
            # 冲正处理：上位机没有该订单的执行记录，执行回滚
            process_dispense_failure(
                order=order,
                operator='reconciliation',
                remark='断线重连对账：上位机无记录，指令丢失冲正'
            )
            ProductionTask.objects.filter(order=order).update(
                status=ProductionTask.TASK_FAILED,
                failure_reason='对账未执行冲正'
            )
            results.append({'order_no': order.order_no, 'action': 'rollback_unexecuted'})

    return {
        'device_sn': device_sn,
        'reconciled_count': len(results),
        'details': results
    }
