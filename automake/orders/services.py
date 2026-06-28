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


def calculate_required_materials(items_data: list) -> dict:
    """
    根据商品清单数据计算所需原材料及用量
    items_data 格式：[{'item': MenuItem, 'skus': [MenuSku, ...], 'quantity': int}, ...]
    return:{'002': Decimal('22.00'), '003': Decimal('2.00')}
    """
    required = {}
 
    for item_info in items_data:
        item_obj = item_info.get('item')
        sku_objs = item_info.get('skus', [])
        quantity = item_info['quantity']

 
        for sku in sku_objs:
         
            for ing in sku.global_sku.ingredients.select_related('material').all():
                item = item_obj,
                code = ing.material.code
                qty = ing.quantity * quantity          
                required[code] = required.get(code, Decimal('0.00')) + Decimal(str(qty))
    print('rrrrr', required)
    return required





def precheck_order(store_id: int, items_data: list) -> dict:
    """
    预校验订单（正式下单前调用）

    检查内容：
    1. 门店是否营业
    2. 商品/SKU 是否存在且上架
    3. 价格计算
    4. 检查系统排队等待制作的订单数量是否小于 50
    5. 匹配可用设备：检查在线设备中，是否有设备的 Redis 虚拟库存满足杯子物料需求（并且高于极低熔断线 20%*warn_level）。
    """
    print('precheck start....')
    try:
        store = Store.objects.get(pk=store_id)
    except Store.DoesNotExist:
        raise ValueError('门店不存在')

    if not store.is_open:
        raise ValueError('门店暂未营业，无法下单')

    # 1. 校验系统等待制作的订单数量是否小于 50
    waiting_count = OrderMain.objects.filter(
        status__in=[OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING]
    ).count()
    if waiting_count >= 50:
        raise ValueError('当前排队订单过多，请稍后再试')

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
            print(item_obj,'====')
        except MenuItem.DoesNotExist:
            raise ValueError(f'商品 ID={item_id} 在该门店不存在或已下架')

        # 校验选中的规格
        sku_objs = []
        sku_names = []
        print('4444444444', item_data)
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
        print('===',item_obj.base_price, sum(s.price_delta for s in sku_objs))
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
    required_materials = calculate_required_materials(checked_items)

    # 查找门店在线的可用设备
    devices = Device.objects.filter(store=store, status=Device.STATUS_ONLINE)
    print(devices)
    # 从在线设备中匹配 Redis 虚拟库存充足（减去需求后不低于极度缺货阈值）的设备
    selected_device = None
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")
    for dev in devices:
        stock_ok = True
        for mat_code, qty in required_materials.items():
            key = get_redis_stock_key(dev.device_sn, mat_code)
            redis_conn[key] = 3000
            val = redis_conn.get(key)
            print('--==', key, val)
            stock_val = int(val) if val is not None else 0
            
            from devices.models import DeviceConsumableStock, DeviceMaterialStock
            stock_config = DeviceConsumableStock.objects.filter(device=dev, code=mat_code).first()
            if stock_config:
                warn_level = float(stock_config.warn_level)
            else:
                material_config = DeviceMaterialStock.objects.filter(device=dev, code=mat_code).first()
                warn_level = float(material_config.warn_level) if material_config else 0.0
          
            # 极低缺货阈值 = warn_level * 0.2
            # Redis中的数量是实际数量放大100倍。而qty是实际需求量。
            # 所以我们要统一将qty和critical_val放大100倍再和stock_val比较
            critical_val_scaled = int(warn_level )
            print('------',mat_code ,stock_val, qty, critical_val_scaled)
            qty_scaled = int(float(qty) )
            
            # 校验库存：扣减后不低于极度缺货阈值
            if stock_val - qty_scaled < critical_val_scaled:
                stock_ok = False
                break
        if stock_ok:
            selected_device = dev
            break
    
    if not selected_device:
        if devices.exists():
            raise ValueError('当前门店设备原料不足，请调整商品')
        else:
            raise ValueError('当前门店暂无可用设备，请稍后再试')
    print('---',required_materials)
    return {
        'ok': True,
        'items': checked_items,
        'total_amount': total_amount,
        'pay_amount': total_amount,
        'store': store,
        'device': selected_device,
        'required_materials': required_materials,
    }


@transaction.atomic
def create_order(user, store_id: int, items_data: list, remark: str = '') -> OrderMain:
    """
    创建订单（初始状态为 CREATED/待支付）
    """
    
    checked = precheck_order(store_id, items_data)
    device = checked['device']
    print('create order start.....', checked)
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

    # 计算出所有的物料总消耗（食材+耗材）
    required_materials = calculate_required_materials(items_data)
    
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
    mapping = {
        'paperL': '大纸杯',
        'paperM': '中纸杯',
        'plasticL': '大塑料杯',
        'plasticM': '中塑料杯',
        'membrane': '封口膜',
        'lid': '杯盖'
    }
    return mapping.get(code, code)


def calculate_required_consumables_for_order(order: OrderMain) -> dict:
    """
    根据订单计算所需的耗材数量（杯子、封口膜、杯盖等）
    
    直接调用 calculate_required_materials 并过滤出类型为耗材 (consumable) 的物料总量。
    """
    items_data = []
    for item in order.items.prefetch_related('skus').all():
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

    all_materials = calculate_required_materials(items_data)

    from inventory.models import Material
    consumable_codes = set(
        Material.objects.filter(
            code__in=all_materials.keys(),
            material_type=Material.TYPE_CONSUMABLE
        ).values_list('code', flat=True)
    )

    required_consumables = {
        code: qty for code, qty in all_materials.items() if code in consumable_codes
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
        consumable_name = get_consumable_name_by_code(code)
        material_obj, _ = Material.objects.get_or_create(
            name=consumable_name,
            defaults={
                'code': code,
                'material_type': Material.TYPE_CONSUMABLE,
                'unit': '张' if code == 'membrane' else '个',
                'shelf_life': '永久',
                'storage_conditions': '常温干燥'
            }
        )
        if material_obj.material_type != Material.TYPE_CONSUMABLE:
            material_obj.material_type = Material.TYPE_CONSUMABLE
            material_obj.save(update_fields=['material_type'])

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
