"""
订单业务函数模块

将核心业务逻辑从 View 中抽离，便于复用和测试。
函数职责单一，异常向上抛出，由 View 层统一处理。
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from menus.models import MenuItem, MenuSku, MaterialStock
from stores.models import Store
from devices.models import Device
from .models import OrderMain, OrderItem, OrderStatusLog, ProductionTask

logger = logging.getLogger(__name__)


RECIPES = {
    "美式咖啡": {"coffee_bean": 15.0},
    "拿铁咖啡": {"coffee_bean": 15.0, "fresh_milk": 150.0},
}


def calculate_required_materials(items_data: list) -> dict:
    """
    根据商品清单数据计算所需原材料及用量
    items_data 格式：[{'item': MenuItem, 'quantity': int}, ...]
    """
    required = {}
    for item_info in items_data:
        item = item_info.get('item')
        if not item:
            continue
        quantity = item_info['quantity']
        item_name = item.name

        # 模糊匹配配方
        recipe = None
        for name, rep in RECIPES.items():
            if name in item_name:
                recipe = rep
                break
        if not recipe:
            if "拿铁" in item_name or "奶" in item_name:
                recipe = RECIPES["拿铁咖啡"]
            else:
                recipe = RECIPES["美式咖啡"]

        for code, qty in recipe.items():
            required[code] = required.get(code, 0.0) + (qty * quantity)
    return required


def precheck_order(store_id: int, items_data: list) -> dict:
    """
    预校验订单（正式下单前调用）

    检查内容：
    1. 门店是否营业
    2. 商品/SKU 是否存在且上架
    3. 价格计算
    4. 设备库存校验：根据配方耗量校验门店下是否有可用在线设备的物料库存满足需求。

    :param store_id: 门店 ID
    :param items_data: 商品列表，格式 [{'sku_id': 1, 'quantity': 2}, ...]
    :return: {
        'ok': True,
        'items': [{'item': ..., 'sku': ..., 'quantity': ..., 'unit_price': ..., 'subtotal': ...}],
        'total_amount': ...,
        'store': <Store>
    }
    :raises: ValueError 当校验不通过时
    """
    # 1. 校验门店
    try:
        store = Store.objects.get(pk=store_id)
    except Store.DoesNotExist:
        raise ValueError('门店不存在')

    if not store.is_open:
        raise ValueError('门店暂未营业，无法下单')

    # 2. 校验商品和价格
    checked_items = []
    total_amount = 0

    for item_data in items_data:
        quantity = item_data['quantity']
        sku_id = item_data.get('sku_id')
        item_id = item_data.get('item_id')

        if sku_id:
            # 有规格的商品：通过 SKU 查找
            try:
                sku = MenuSku.objects.select_related('item').get(
                    pk=sku_id,
                    is_active=True,
                    item__is_active=True,
                    item__store=store,
                )
            except MenuSku.DoesNotExist:
                raise ValueError(f'规格 ID={sku_id} 不存在或已下架')

            item = sku.item
            unit_price = sku.final_price
            item_name = item.name
            sku_name = sku.name

        elif item_id:
            # 无规格商品：直接通过商品 ID
            try:
                item = MenuItem.objects.get(
                    pk=item_id,
                    is_active=True,
                    store=store,
                )
            except MenuItem.DoesNotExist:
                raise ValueError(f'商品 ID={item_id} 不存在或已下架')

            sku = None
            unit_price = item.base_price
            item_name = item.name
            sku_name = ''

        else:
            raise ValueError('item_id 和 sku_id 不能同时为空')

        subtotal = unit_price * quantity
        total_amount += subtotal

        checked_items.append({
            'item': item,
            'sku': sku,
            'quantity': quantity,
            'unit_price': unit_price,
            'subtotal': subtotal,
            'item_name': item_name,
            'sku_name': sku_name,
        })

    # 3. 计算配方与物料库存校验（为订单提前匹配分配可用设备）
    required_materials = calculate_required_materials(checked_items)
    
    devices = Device.objects.filter(store=store, status=Device.STATUS_ONLINE)
    selected_device = None

    for dev in devices:
        stocks = MaterialStock.objects.filter(device=dev)
        stock_dict = {s.material_code: s for s in stocks}

        is_match = True
        for code, qty in required_materials.items():
            if code not in stock_dict:
                is_match = False
                break
            stock = stock_dict[code]
            available = stock.current_quantity - stock.locked_quantity
            if available < qty:
                is_match = False
                break
        
        if is_match:
            selected_device = dev
            break

    if not selected_device:
        raise ValueError('当前门店暂无可用设备或设备原料库存不足，请稍后再试')

    return {
        'ok': True,
        'items': checked_items,
        'total_amount': total_amount,
        'pay_amount': total_amount,  # 暂无优惠，实付 = 总额
        'store': store,
        'device': selected_device,
        'required_materials': required_materials,
    }


@transaction.atomic
def create_order(user, store_id: int, items_data: list, remark: str = '') -> OrderMain:
    """
    创建订单（依赖 precheck_order 成功）

    流程：
    1. 再次执行 precheck（防止并发期间库存状态变化，并选定可用设备）
    2. 加锁锁定该设备的 MaterialStock 物料记录，防超卖，并增加 locked_quantity
    3. 写入 order_main 并关联预分配的设备
    4. 写入 order_item（明细）
    5. 写入 order_status_log（待支付状态）

    :param user: 下单用户对象
    :param store_id: 门店 ID
    :param items_data: 商品列表
    :param remark: 备注
    :return: 创建好的 OrderMain 对象
    :raises: ValueError 当校验失败时
    """
    # 再次预校验并确定执行设备
    checked = precheck_order(store_id, items_data)
    device = checked['device']
    required_materials = checked['required_materials']
    
    # 锁定物料库存记录，双重验证
    codes = list(required_materials.keys())
    stocks = MaterialStock.objects.select_for_update().filter(device=device, material_code__in=codes)
    stock_dict = {s.material_code: s for s in stocks}

    for code, qty in required_materials.items():
        if code not in stock_dict:
            raise ValueError(f'设备未配置物料 {code}')
        stock = stock_dict[code]
        available = stock.current_quantity - stock.locked_quantity
        if available < qty:
            raise ValueError(f'物料 {stock.material_name} ({code}) 库存不足，无法锁仓')

    # 更新设备锁定库存量
    for code, qty in required_materials.items():
        stock = stock_dict[code]
        stock.locked_quantity += Decimal(str(qty))
        stock.save(update_fields=['locked_quantity', 'updated_at'])

    # 创建订单主记录
    order = OrderMain.objects.create(
        user=user,
        store=checked['store'],
        device=device,  # 下单直接绑定设备
        total_amount=checked['total_amount'],
        discount_amount=0,
        pay_amount=checked['pay_amount'],
        remark=remark,
        status=OrderMain.STATUS_PENDING_PAY,
    )

    # 批量创建订单明细（减少 SQL 次数）
    order_items = []
    for item_info in checked['items']:
        order_items.append(OrderItem(
            order=order,
            item=item_info['item'],
            sku=item_info['sku'],
            item_name=item_info['item_name'],
            sku_name=item_info['sku_name'],
            unit_price=item_info['unit_price'],
            quantity=item_info['quantity'],
            subtotal=item_info['subtotal'],
        ))
    OrderItem.objects.bulk_create(order_items)

    # 写入第一条状态记录（待支付）
    OrderStatusLog.objects.create(
        order=order,
        from_status='',
        to_status=OrderMain.STATUS_PENDING_PAY,
        operator='system',
        remark='用户下单，预锁设备原料库存，等待支付',
    )

    logger.info(f'订单创建成功: order_no={order.order_no}, user_id={user.id}, 预锁设备 {device.device_sn} 原料库存: {required_materials}')
    return order


@transaction.atomic
def create_production_task(order: OrderMain) -> ProductionTask:
    """
    创建生产任务（支付成功后调用）

    流程：
    1. 获取下单时预分配绑定的设备
    2. 创建 ProductionTask 记录
    """
    # 获取下单时预分配绑定的设备
    device = order.device
    if not device:
        # 兼容历史数据兜底
        device = Device.objects.filter(
            store=order.store,
            status=Device.STATUS_ONLINE
        ).first()

    if not device:
        logger.error(f'创建生产任务失败：门店 {order.store_id} 无在线设备，order_no={order.order_no}')
        raise ValueError('无可用设备，无法创建生产任务')

    # 构建下发给上位机的命令数据
    command_payload = {
        'order_no': order.order_no,
        'items': [
            {
                'item_name': item.item_name,
                'sku_name': item.sku_name,
                'quantity': item.quantity,
            }
            for item in order.items.all()
        ],
    }

    task = ProductionTask.objects.create(
        order=order,
        device=device,
        status=ProductionTask.TASK_PENDING,
        command_payload=command_payload,
    )

    logger.info(f'生产任务创建成功: order_no={order.order_no}, device={device.device_sn}')
    return task


def update_order_status(order: OrderMain, new_status: str,
                        operator: str = 'system', remark: str = '') -> None:
    """
    更新订单状态并记录状态日志

    :param order: 订单对象
    :param new_status: 新状态
    :param operator: 操作方（system/user/device）
    :param remark: 备注
    """
    old_status = order.status
    order.status = new_status

    # 若状态为完成，记录完成时间
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
    取消订单并释放锁定的库存

    :param order: 订单对象
    :param operator: 操作人/系统
    :param remark: 备注
    """
    if not order.can_cancel:
        raise ValueError(f'订单状态 [{order.get_status_display()}] 不允许取消')

    # 若处于未支付状态且已分配设备，则释放对应的锁定库存量
    if order.device and order.status == OrderMain.STATUS_PENDING_PAY:
        items_data = [{'item': item.item, 'quantity': item.quantity} for item in order.items.all()]
        required_materials = calculate_required_materials(items_data)

        if required_materials:
            from menus.models import MaterialStock
            codes = list(required_materials.keys())
            stocks = MaterialStock.objects.select_for_update().filter(device=order.device, material_code__in=codes)
            stock_dict = {s.material_code: s for s in stocks}

            for code, qty in required_materials.items():
                if code in stock_dict:
                    stock = stock_dict[code]
                    qty_dec = Decimal(str(qty))
                    if stock.locked_quantity >= qty_dec:
                        stock.locked_quantity -= qty_dec
                    else:
                        stock.locked_quantity = 0
                    stock.save(update_fields=['locked_quantity', 'updated_at'])
            
            logger.info(f'订单 {order.order_no} 被取消，已释放设备 {order.device.device_sn} 锁定的原料库存: {required_materials}')

    update_order_status(
        order=order,
        new_status=OrderMain.STATUS_CANCELLED,
        operator=operator,
        remark=remark
    )
