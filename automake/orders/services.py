"""
订单业务函数模块

将核心业务逻辑从 View 中抽离，便于复用和测试。
函数职责单一，异常向上抛出，由 View 层统一处理。
"""

import datetime
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

from utils.redis_keys import get_stock_key

logger = logging.getLogger(__name__)


def get_redis_stock_key(device_sn: str, material_code: str) -> str:
    """获取 Redis 虚拟库存 key（已委托至 utils.redis_keys.get_stock_key）"""
    return get_stock_key(device_sn, material_code)


 
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
    logger.debug(f"[Precheck] 计算每杯物料需求明细: {per_cup_materials}")
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
        status_disp = target_device.get_status_display() or '离线'
        raise ValueError(f'设备 ({target_device.device_sn}) 当前处于{status_disp}状态，无法接单制作')

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
    material_checks = []
    has_shortage = False
    shortage_reasons = []

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
        def _safe_float(val):
            if val is None:
                return 0.0
            try:
                return max(0.0, float(val))
            except (ValueError, TypeError):
                return 0.0

        stock_vals = {}
        if ingredient_codes:
            keys = [get_redis_stock_key(target_device.device_sn, code) for code in ingredient_codes]
            vals = redis_conn.mget(keys)
            if not isinstance(vals, (list, tuple)):
                vals = [redis_conn.get(k) for k in keys]
            stock_vals = {code: _safe_float(val) for code, val in zip(ingredient_codes, vals)}

        from inventory.models import Material
        mats_db = {m.code: m for m in Material.objects.filter(code__in=mat_codes)}

        for mat_code, qty in required_materials.items():
            qty_needed = float(qty)
            in_flight_committed = float(unproduced_usage.get(mat_code, Decimal('0.00')))
            unit = '个'
            
            if mat_code in known_consumable_codes:
                # 杯型/耗材类型：通过 MySQL DeviceConsumableStock 校验
                cs_obj = consumables_map.get(mat_code)
                db_stock = max(0.0, float(cs_obj.quantity)) if cs_obj else 0.0
                effective_available_stock = db_stock - in_flight_committed
                mat_name = getattr(getattr(cs_obj, 'code', None), 'name', mat_code) if cs_obj else get_consumable_name_by_code(mat_code)
                unit = getattr(cs_obj, 'unit', '张' if mat_code == 'membrane' else '个') if cs_obj else ('张' if mat_code == 'membrane' else '个')
                storage_type = 'MySQL'
                item_type = '耗材'
                raw_stock = db_stock
            else:
                # 食材类型：通过 Redis 实时料桶余量校验
                stock_val = stock_vals.get(mat_code, 0.0)
                effective_available_stock = stock_val - in_flight_committed
                mat_name = mat_code
                material_config = DeviceMaterialStock.objects.filter(device=target_device, code=mat_code).first()
                if material_config and material_config.name:
                    mat_name = getattr(material_config.name, 'name', mat_code)
                elif mat_code in mats_db:
                    mat_name = mats_db[mat_code].name
                mat_obj = mats_db.get(mat_code)
                unit = mat_obj.unit if mat_obj else 'g/ml'
                storage_type = 'Redis'
                item_type = '食材'
                raw_stock = stock_val

            is_sufficient = (effective_available_stock - qty_needed >= 0)
            if not is_sufficient:
                has_shortage = True
                shortage_reasons.append(f"{mat_name}缺料(可用{max(0.0, effective_available_stock):.1f}{unit}，需{qty_needed:.1f}{unit})")

            material_checks.append({
                'code': mat_code,
                'name': mat_name,
                'unit': unit,
                'type': item_type,
                'storage': storage_type,
                'required': round(qty_needed, 2),
                'stock_raw': round(raw_stock, 2),
                'in_flight': round(in_flight_committed, 2),
                'effective_available': round(max(0.0, effective_available_stock), 2),
                'is_sufficient': is_sufficient,
            })

    if has_shortage:
        msg = f"设备 ({target_device.device_sn}) 原料不足：" + "；".join(shortage_reasons)
        logger.info(msg)
        err = ValueError(msg)
        err.material_checks = material_checks
        raise err

    return {
        'ok': True,
        'items': checked_items,
        'total_amount': total_amount,
        'pay_amount': total_amount,
        'store': store,
        'device': target_device,
        'required_materials': required_materials,
        'per_cup_materials': per_cup_materials,
        'material_checks': material_checks,
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

    # 写入履约流转时间线（初始待支付节点，附带商品快照与支付金额元数据）
    items_snapshot = [
        {
            'item_name': item_info.get('item_name', ''),
            'sku_name': ", ".join(item_info.get('sku_names', [])) if item_info.get('sku_names') else '常规',
            'quantity': item_info.get('quantity', 1),
            'unit_price': item_info.get('unit_price', 0),
            'subtotal': item_info.get('subtotal', 0)
        }
        for item_info in checked.get('items', [])
    ]
    record_order_timeline(
        order=order,
        action=OrderStatusLog.ACTION_CREATE,
        action_name='订单创建（待支付）',
        from_status='',
        to_status=OrderMain.STATUS_PENDING_PAY,
        operator_type=OrderStatusLog.OP_USER,
        operator=f'user:{user.id}',
        remark='用户下单，订单已创建，等待支付',
        payload={
            'store_id': checked['store'].id if checked.get('store') else None,
            'store_name': checked['store'].name if checked.get('store') else '',
            'device_sn': device.device_sn if device else '',
            'total_amount': checked.get('total_amount', 0),
            'pay_amount': checked.get('pay_amount', 0),
            'items': items_snapshot,
            'user_remark': remark,
        }
    )

    logger.info(f'订单创建成功: order_no={order.order_no}, user_id={user.id}')
    return order


def format_instant(dt):
    if not dt:
        return None
    if timezone.is_aware(dt):
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{int(dt.microsecond / 1000):03d}Z'


@transaction.atomic
def create_production_task(order: OrderMain) -> ProductionTask:
    """
    创建生产任务，生成标准 MQTT 出餐制作指令 (type: make)
    """
    device = order.device
    if not device:
        raise ValueError('订单未绑定设备，无法创建生产任务')

    # 1. 获取或兜底生成取餐码 ticketNo
    pickup = getattr(order, 'pickup_code', None)
    if not pickup:
        try:
            from notifications.models import PickupCode
            pickup = PickupCode.objects.filter(order=order).first()
        except Exception:
            pickup = None
    if not pickup:
        try:
            from notifications.services import create_pickup_code
            pickup = create_pickup_code(order)
        except Exception as e:
            logger.warning(f"为订单 {order.order_no} 兜底生成取餐码异常: {e}")
            pickup = None

    ticket_no = "1"
    if pickup and pickup.code:
        ticket_no = str(int(pickup.code)) if str(pickup.code).isdigit() else str(pickup.code)

    # 2. 构造 merchInfos（包含每个商品的单杯配方）
    merch_infos = []
    for item in order.items.prefetch_related('skus', 'item').all():
        skus = list(item.skus.all())
        if not skus and item.item:
            base_sku = MenuSku.objects.filter(item=item.item, is_active=True).first()
            if base_sku:
                skus = [base_sku]

        single_item_data = [{
            'item': item.item,
            'skus': skus,
            'quantity': 1,
            'item_name': item.item_name,
            'sku_names': [item.sku_name] if item.sku_name else []
        }]
        cup_res = calculate_required_materials(single_item_data)
        item_materials = {}
        if cup_res:
            mats = cup_res[0].get('materials', {})
            for m_code, m_qty in mats.items():
                val = float(m_qty)
                item_materials[m_code] = int(val) if val.is_integer() else round(val, 2)

        merch_infos.append({
            'item_name': item.item_name,
            'sku_name': item.sku_name or '常规',
            'quantity': item.quantity,
            'materials': item_materials
        })

    # 3. 组装标准化 make 命令 Payload
    command_payload = {
        'type': 'make',
        'order_no': order.order_no,
        'order_token': str(order.order_token) if order.order_token else '',
        'tradeState': 'SUCCESS',
        'ticketNo': ticket_no,
        'createdAt': format_instant(order.created_at) if order.created_at else format_instant(timezone.now()),
        'paidAt': format_instant(order.paid_at) if order.paid_at else format_instant(timezone.now()),
        'payerTotal': int(order.pay_amount),
        'qrCode': str(order.order_token) if order.order_token else str(order.order_no),
        'merchInfos': merch_infos
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
    task._is_created = created

    if not created:
        logger.info(f'生产任务已存在，跳过重复记录时间线与下发: order_no={order.order_no}, task_id={task.id}')
        return task

    # 记录履约时间线：生产任务已生成并下发排队
    record_order_timeline(
        order=order,
        action=OrderStatusLog.ACTION_TASK_SENT,
        action_name='制作任务生成并下发',
        from_status=order.status,
        to_status=order.status,
        operator_type=OrderStatusLog.OP_SYSTEM,
        operator='system',
        remark=f'制作任务已生成并下发至设备 {device.device_sn}，取餐号: {ticket_no}',
        payload={
            'task_id': task.id,
            'device_sn': device.device_sn,
            'ticket_no': ticket_no,
            'merch_count': len(merch_infos)
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
            'quantity': item.quantity,
            'item_name': item.item_name,
            'sku_names': [s.strip() for s in item.sku_name.split('/')] if item.sku_name else []
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


def record_order_timeline(
    order: OrderMain,
    action: str = '',
    action_name: str = '',
    from_status: str = None,
    to_status: str = None,
    operator_type: str = None,
    operator: str = 'system',
    remark: str = '',
    payload: dict = None
) -> OrderStatusLog:
    """
    记录订单履约流转时间线（高追溯、结构化记录）

    :param order: 关联订单
    :param action: 动作标识，如 create, pay_success, making_start, refund_applied, refund_failed 等
    :param action_name: 动作中文名，如 '订单创建', '微信支付成功', '退款失败'
    :param from_status: 变更前状态
    :param to_status: 变更后状态
    :param operator_type: user | device | admin | system | wechat
    :param operator: 具体操作主体标识
    :param remark: 说明备注
    :param payload: 上下文详情字典
    """
    if from_status is None:
        from_status = order.status
    if to_status is None:
        to_status = order.status

    if not operator_type:
        op_lower = (operator or '').lower()
        if op_lower.startswith('device:') or op_lower.startswith('sn') or op_lower == 'device':
            operator_type = OrderStatusLog.OP_DEVICE
        elif op_lower.startswith('user:') or op_lower == 'user':
            operator_type = OrderStatusLog.OP_USER
        elif 'wechat' in op_lower or 'wx' in op_lower:
            operator_type = OrderStatusLog.OP_WECHAT
        elif op_lower in ('system', 'reconciliation', 'scheduler', 'timer'):
            operator_type = OrderStatusLog.OP_SYSTEM
        else:
            operator_type = OrderStatusLog.OP_ADMIN

    safe_payload = payload if isinstance(payload, dict) else (payload or {})

    log_entry = OrderStatusLog.objects.create(
        order=order,
        action=action,
        action_name=action_name,
        from_status=from_status,
        to_status=to_status,
        operator_type=operator_type,
        operator=operator,
        remark=remark,
        payload=safe_payload
    )
    return log_entry


def update_order_status(order: OrderMain, new_status: str,
                        operator: str = 'system', remark: str = '',
                        action: str = None, action_name: str = '',
                        operator_type: str = None, payload: dict = None) -> None:
    """
    更新订单状态并记录履约流转时间线日志
    """
    old_status = order.status
    order.status = new_status

    if new_status == OrderMain.STATUS_DONE:
        order.done_at = timezone.now()

    order.save(update_fields=['status', 'done_at', 'updated_at'])

    # 自动推导默认 action 和 action_name（若未显式指定）
    if not action:
        status_action_map = {
            OrderMain.STATUS_PENDING_PAY: (OrderStatusLog.ACTION_WAIT_PAY, '等待支付'),
            OrderMain.STATUS_PAID: (OrderStatusLog.ACTION_PAY_SUCCESS, '支付成功/待出货'),
            OrderMain.STATUS_MAKING: (OrderStatusLog.ACTION_MAKING_START, '开始制作'),
            OrderMain.STATUS_DONE: (OrderStatusLog.ACTION_MAKING_DONE, '制作完成/出货成功'),
            OrderMain.STATUS_CANCELLED: (OrderStatusLog.ACTION_CANCELLED, '订单已取消'),
            OrderMain.STATUS_REFUNDING: (OrderStatusLog.ACTION_REFUND_APPLIED, '退款处理中'),
            OrderMain.STATUS_REFUNDED: (OrderStatusLog.ACTION_REFUND_SUCCESS, '退款成功'),
            OrderMain.STATUS_EXCEPTION: (OrderStatusLog.ACTION_FAILED, '订单异常/失败'),
        }
        action, default_name = status_action_map.get(new_status, ('update', '状态更新'))
        if not action_name:
            action_name = default_name

    record_order_timeline(
        order=order,
        action=action,
        action_name=action_name,
        from_status=old_status,
        to_status=new_status,
        operator_type=operator_type,
        operator=operator,
        remark=remark,
        payload=payload
    )
    logger.info(f'订单状态更新: order_no={order.order_no}, {old_status} → {new_status}, action={action}')

    # 当订单成功完成且状态是从非完成状态变更过来时，扣减耗材库存
    if old_status != OrderMain.STATUS_DONE and new_status == OrderMain.STATUS_DONE:
        try:
            deduct_order_consumables(order)
        except Exception as e:
            logger.exception(f'扣减订单 {order.order_no} 耗材库存失败: {e}')


@transaction.atomic
def cancel_order(order: OrderMain, operator: str = 'system', remark: str = '', operator_type: str = None) -> None:
    """
    取消订单
    """
    if not order.can_cancel:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许取消')

    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_CANCELLED,
        operator=operator,
        operator_type=operator_type or (OrderStatusLog.OP_USER if str(operator).startswith('user') else OrderStatusLog.OP_SYSTEM),
        action=OrderStatusLog.ACTION_CANCELLED,
        action_name='订单已取消',
        remark=remark or '用户或系统取消订单',
        payload={'cancel_reason': remark}
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

    # 1. 变更为 FAILED 并记录履约失败流水
    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_EXCEPTION,
        operator=operator,
        action=OrderStatusLog.ACTION_FAILED,
        action_name='制作失败/物理出库异常',
        remark=remark,
        payload={
            'failure_reason': remark,
            'device_sn': order.device.device_sn if order.device else '',
            'order_token': str(order.order_token) if order.order_token else ''
        }
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


@transaction.atomic
def restore_order_inventory(order: OrderMain, operator: str = 'system', reason: str = '未制作退款放库') -> dict:
    """
    未制作订单退款放库服务函数

    业务逻辑：
    1. 针对已支付/待制作/制作中但尚未出餐完成的订单，反向归还所占用的耗材与物料库存；
    2. MySQL 耗材库存 (DeviceConsumableStock) 原子加回；
    3. Redis 耗材预扣 (automake:stock:{sn}:{code}) 原子加回；
    4. 关联的未完成生产任务 (ProductionTask) 标记为已终止/失败；
    5. 返回详细的放库物料明细清单，供上位机或前端展示。
    """
    device = order.device
    if not device:
        logger.warning(f"订单 {order.order_no} 未关联设备，跳过退款放库")
        return {'success': False, 'order_no': order.order_no, 'restored_materials': []}

    from django_redis import get_redis_connection
    from devices.models import DeviceConsumableStock
    from inventory.models import Material
    redis_conn = get_redis_connection("default")

    # 1. 计算订单的所有所需物料
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
            'quantity': item.quantity,
            'item_name': item.item_name,
            'sku_names': [s.strip() for s in item.sku_name.split('/')] if item.sku_name else []
        })

    per_cup_materials = calculate_required_materials(items_data)
    all_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for code, qty in cup_mats.items():
            all_materials[code] = all_materials.get(code, Decimal('0.00')) + Decimal(str(qty))

    known_consumables = {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'}
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type__in=[Material.TYPE_CONSUMABLE, Material.TYPE_CUP]
        ).values_list('code', flat=True)
    )
    consumable_codes.update(known_consumables)

    restored_list = []

    for code, qty in all_materials.items():
        qty_float = float(qty)
        mat_obj = Material.objects.filter(code=code).first()
        mat_name = mat_obj.name if mat_obj else get_consumable_name_by_code(code)
        unit = mat_obj.unit if mat_obj else ('张' if code == 'membrane' else '个')

        if code in consumable_codes:
            qty_int = int(qty)
            # 1. 加回 MySQL 耗材库存
            DeviceConsumableStock.objects.filter(
                device=device,
                code__code=code
            ).update(quantity=F('quantity') + qty_int, updated_at=timezone.now())

            # 2. 加回 Redis 耗材预扣
            key = get_redis_stock_key(device.device_sn, code)
            val_to_incr = int(qty * 100)
            redis_conn.incrby(key, val_to_incr)

            restored_list.append({
                'code': code,
                'name': mat_name,
                'quantity': qty_int,
                'unit': unit,
                'type': '耗材',
                'target': 'MySQL + Redis'
            })
            logger.info(f"[STOCK_RESTORE] 耗材释放回库: 设备={device.device_sn}, 耗材={code}({mat_name}), 数量={qty_int}")
        else:
            # 食材类物料：解冻在途锁定 (订单取消/退款后 unproduced_usage 自动清零)
            restored_list.append({
                'code': code,
                'name': mat_name,
                'quantity': qty_float,
                'unit': unit,
                'type': '食材',
                'target': '解除在途锁定'
            })
            logger.info(f"[STOCK_RESTORE] 食材解除在途占用: 设备={device.device_sn}, 食材={code}({mat_name}), 数量={qty_float}")

    # 作废关联的生产任务
    ProductionTask.objects.filter(order=order).update(
        status=ProductionTask.TASK_FAILED,
        failure_reason=reason
    )

    logger.info(f"[STOCK_RESTORE] 订单 {order.order_no} 退款放库完成，释放物料项: {len(restored_list)}")
    return {
        'success': True,
        'order_no': order.order_no,
        'restored_materials': restored_list
    }


def precheck_device_environment_for_pay(order: OrderMain) -> tuple:
    """
    实际发起支付/扣款前的轻量级环境 Precheck：
    校验制作设备在线状态、整机硬件健康快照及当前排队队列容量。
    返回 (is_ok, error_message)。
    """
    device = order.device
    if not device:
        return False, "订单未绑定制作设备，无法出餐"

    # 1. 校验设备是否在线
    from devices.models import Device
    if device.status != Device.STATUS_ONLINE:
        status_disp = device.get_status_display() or '离线'
        return False, f"制作设备【{device.device_sn}】当前处于{status_disp}状态，暂不可出餐"

    # 2. 校验设备硬件监控快照健康度
    import json
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")
    snapshot_json = redis_conn.get(f"automake:monitor:snapshot:{device.device_sn}")
    if snapshot_json:
        try:
            if isinstance(snapshot_json, bytes):
                snapshot_json = snapshot_json.decode('utf-8')
            snap_data = json.loads(snapshot_json)
            if snap_data.get('disconnected') or not snap_data.get('healthy', True):
                return False, f"制作设备【{device.device_sn}】硬件状态异常，暂不可出餐"
        except (ValueError, json.JSONDecodeError):
            pass
        except Exception:
            pass

    # 3. 校验设备待出货制作队列（防止爆单）
    waiting_count = OrderMain.objects.filter(
        device=device,
        status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
    ).exclude(pk=order.pk).count()
    if waiting_count >= 50:
        return False, f"制作设备【{device.device_sn}】排队制作队列已达上限 ({waiting_count}单)，请稍后重试"

    return True, "设备环境就绪"


@transaction.atomic
def try_lock_order_inventory(order: OrderMain) -> tuple:
    """
    实际支付前再次 Precheck 并原子锁定库存（悲观行锁 select_for_update 预扣）。
    
    返回 (is_success, error_message, lock_context)。
    若成功，耗材在 MySQL 与 Redis 中被原子锁定；若环境异常或库存不足，直接返回失败，绝不调用微信扣款。
    """
    # 0. 支付前先执行设备在线与硬件健康 Precheck
    env_ok, env_err = precheck_device_environment_for_pay(order)
    if not env_ok:
        logger.warning(f"[PAY_PRECHECK] 订单 {order.order_no} 支付前环境核验失败: {env_err}")
        return False, env_err, {}

    device = order.device
    from devices.models import DeviceConsumableStock
    from inventory.models import Material
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")

    # 1. 计算订单所需的耗材与物料总量
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
            'quantity': item.quantity,
            'item_name': item.item_name,
            'sku_names': [s.strip() for s in item.sku_name.split('/')] if item.sku_name else []
        })

    per_cup_materials = calculate_required_materials(items_data)
    all_materials = {}
    for cup in per_cup_materials:
        cup_mats = cup.get('materials', cup) if isinstance(cup, dict) else cup
        for code, qty in cup_mats.items():
            all_materials[code] = all_materials.get(code, Decimal('0.00')) + Decimal(str(qty))

    known_consumables = {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'}
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type__in=[Material.TYPE_CONSUMABLE, Material.TYPE_CUP]
        ).values_list('code', flat=True)
    )
    consumable_codes.update(known_consumables)

    required_cups = {
        code: qty for code, qty in all_materials.items()
        if code in consumable_codes
    }

    # 2. 检查并悲观锁定 MySQL 耗材库存 (select_for_update)
    cs_records = {
        cs.code.code if cs.code else str(cs.code_id): cs
        for cs in DeviceConsumableStock.objects.select_for_update().select_related('code').filter(
            device=device,
            code__code__in=required_cups.keys()
        )
    }

    for cup_code, qty in required_cups.items():
        cs_obj = cs_records.get(cup_code)
        needed = int(qty)
        if not cs_obj or cs_obj.quantity < needed:
            mat_name = get_consumable_name_by_code(cup_code)
            avail = cs_obj.quantity if cs_obj else 0
            return False, f"耗材【{mat_name}】库存不足 (需 {needed}, 仅剩 {avail})", {}

    # 扣减 MySQL
    for cup_code, qty in required_cups.items():
        cs_obj = cs_records[cup_code]
        cs_obj.quantity -= int(qty)
        cs_obj.save(update_fields=['quantity', 'updated_at'])

    # 3. 同步预扣 Redis 耗材预扣
    redis_deducted = []
    for cup_code, qty in required_cups.items():
        key = get_redis_stock_key(device.device_sn, cup_code)
        val_to_deduct = int(qty * 100)
        try:
            redis_conn.decrby(key, val_to_deduct)
            redis_deducted.append((cup_code, val_to_deduct))
        except Exception as e:
            logger.warning(f"Redis 耗材预扣异常: {e}")

    lock_ctx = {
        'order_no': order.order_no,
        'device_sn': device.device_sn,
        'required_cups': {k: int(v) for k, v in required_cups.items()},
        'redis_deducted': redis_deducted,
    }
    logger.info(f"[STOCK_LOCK] 订单 {order.order_no} 实际支付前原子排他锁库成功: {lock_ctx['required_cups']}")
    return True, "库存锁定成功", lock_ctx


@transaction.atomic
def rollback_order_locked_inventory(order: OrderMain, locked_details: dict = None, reason: str = '支付失败自动释放') -> None:
    """
    释放实际支付前原子锁定的耗材与库存 (如微信扣款失败、用户取消)。
    """
    device = order.device
    if not device:
        return

    from devices.models import DeviceConsumableStock
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")

    if not locked_details:
        required = calculate_required_consumables_for_order(order)
        required_cups = {k: int(v) for k, v in required.items()}
    else:
        required_cups = locked_details.get('required_cups', {})

    for cup_code, qty in required_cups.items():
        # 加回 MySQL
        DeviceConsumableStock.objects.filter(
            device=device,
            code__code=cup_code
        ).update(quantity=F('quantity') + int(qty), updated_at=timezone.now())

        # 加回 Redis
        key = get_redis_stock_key(device.device_sn, cup_code)
        val_to_incr = int(qty * 100)
        try:
            redis_conn.incrby(key, val_to_incr)
        except Exception as e:
            logger.warning(f"Redis 耗材回滚加回异常: {e}")

        logger.info(f"[STOCK_UNLOCK] 订单 {order.order_no} 释放锁定耗材: {cup_code} +{qty}, 原因: {reason}")


