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
    """
    required = {}
    
    for item_info in items_data:
        item_obj = item_info.get('item')
        sku_objs = item_info.get('skus', [])
        quantity = item_info['quantity']

        print('====', item_obj, sku_objs)   
        for sku in sku_objs:
            for ing in sku.global_sku.ingredients.select_related('material').all():
                
                code = ing.material.code
                qty = ing.quantity * quantity
                print('--',ing, code, qty)
                required[code] = required.get(code, Decimal('0.00')) + Decimal(str(qty))
    return required


def precheck_order(store_id: int, items_data: list) -> dict:
    """
    预校验订单（正式下单前调用）

    检查内容：
    1. 门店是否营业
    2. 商品/SKU 是否存在且上架
    3. 价格计算
    4. 匹配可用设备：检查在线设备中，是否有设备的 Redis 虚拟库存满足物料需求。
    """
    try:
        store = Store.objects.get(pk=store_id)
    except Store.DoesNotExist:
        raise ValueError('门店不存在')

    if not store.is_open:
        raise ValueError('门店暂未营业，无法下单')

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
            sku_objs = list(MenuSku.objects.select_related('global_sku').filter(
                pk__in=sku_ids,
                item=item_obj,
                is_active=True
            ))
            if len(sku_objs) != len(sku_ids):
                raise ValueError(f'商品规格在此商品下不存在或已禁用')
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
   
    
    # 计算所需原料
    required_materials = calculate_required_materials(checked_items)
    # 查找门店在线且未熔断的可用设备
    devices = Device.objects.filter(store=store, status=Device.STATUS_ONLINE)
    
    # 熔断校验：剔除在 30 秒内有 PENDING_DISPENSE 订单且未响应的设备
    # 目前不需要这个熔断；
    # from datetime import timedelta
    # fused_device_ids = OrderMain.objects.filter(
    #     status=OrderMain.STATUS_PAID,  # 即 pending_dispense
    #     created_at__lt=timezone.now() - timedelta(seconds=30)
    # ).values_list('device_id', flat=True)
    
    # devices = devices.exclude(id__in=fused_device_ids)

    # 从在线设备中匹配 Redis 虚拟库存充足的设备
    selected_device = None
    from django_redis import get_redis_connection
    redis_conn = get_redis_connection("default")
    for dev in devices:
        stock_ok = True
        for code, qty in required_materials.items():
            key = get_redis_stock_key(dev.device_sn, code)
            val = redis_conn.get(key)
            print(key, val)
            stock_val = int(val) if val is not None else 0
            if stock_val < int(qty * 100):
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

    command_payload = {
        'type': 'make',
        'order_no': order.order_no,
        'order_token': order.order_token,
        'OrderToken': order.order_token,
        'quantity': sum(item.quantity for item in order.items.all()),
        'Quantity': sum(item.quantity for item in order.items.all()),
        'items': [
            {
                'item_name': item.item_name,
                'sku_name': item.sku_name,
                'quantity': item.quantity,
            }
            for item in order.items.all()
        ],
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
    2. 利用乐观锁将 DB 库存加回。
    3. 反向补偿 Redis 虚拟库存。
    """
    from devices.models import DeviceMaterialStock
    
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
        # 2. 利用乐观锁将 DB 库存加回
        updated = DeviceMaterialStock.objects.filter(
            device=device,
            material_code=code
        ).update(quantity=F('quantity') + qty)

        if updated == 0:
            # 兼容处理：若不存在该物料记录，则直接创建
            DeviceMaterialStock.objects.create(
                device=device,
                material_code=code,
                quantity=qty
            )

        # 3. 反向补偿 Redis
        key = get_redis_stock_key(device.device_sn, code)
        val = int(qty * 100)
        redis_conn.incrby(key, val)
        logger.info(f'[ROLLBACK] 成功加回库存: order_no={order.order_no}, material={code}, qty={qty}')


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
