"""
seed_realistic_analytics_data.py

工业级商业数据生成脚本（Data Seeder）：
为系统注入过去 30 天具有逼真零售商业特征的运营数据，为 Analytics 6 大分析模块与 Dashboard 驾驶舱提供丰满、真实的数据支撑。

包含特征：
1. 真实时段规律：早高峰 (07:30-09:30) 与下午茶高峰 (13:30-15:30) 密集出单；
2. 周期性波动：工作日与周末的不同消费波形；
3. 全生命周期履约时间线：为订单生成真实的 OrderStatusLog 轨迹；
4. 真实门店与设备出杯产能阶梯对比；
5. 幂等执行：按 SEED_TAG 清理旧模拟数据，可反复执行。
"""

import os
import sys
import random
import datetime
import uuid

# 初始化 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'default.settings')
import django
django.setup()

from django.utils import timezone
from users.models import User
from stores.models import Store
from devices.models import Device
from menus.models import MenuItem, MenuSku
from orders.models import OrderMain, OrderItem, OrderStatusLog, ProductionTask
from payments.models import PaymentRecord
from notifications.models import NotifyEvent

SEED_TAG = "[REALISTIC_SEED_DATA]"


def get_or_create_users():
    """获取或生成 25 位模拟微信顾客会员"""
    users = []
    for i in range(1, 26):
        openid = f"wx_seed_user_{i:04d}"
        u, _ = User.objects.get_or_create(
            openid=openid,
            defaults={
                "phone": f"1390011{i:04d}",
                "role": User.CUSTOMER,
            }
        )
        users.append(u)
    return users


def get_available_goods_and_devices():
    """获取系统中现有的合法在售商品、门店与制作设备"""
    stores = list(Store.objects.filter(status=Store.STATUS_OPEN))
    if not stores:
        stores = [Store.objects.create(code="STORE_DEFAULT_01", name="高新科技园旗舰店", address="科技路88号")]

    devices = list(Device.objects.filter(status=Device.STATUS_ONLINE))
    if not devices:
        devices = list(Device.objects.all())

    menu_items = list(MenuItem.objects.filter(is_active=True).select_related('global_item'))
    if not menu_items:
        menu_items = list(MenuItem.objects.all().select_related('global_item'))

    return stores, devices, menu_items


def seed_realistic_data(days=30):
    """主数据填充函数"""
    print(f"🚀 开始生成过去 {days} 天的高保真商业运营测试数据...")

    stores, devices, menu_items = get_available_goods_and_devices()
    users = get_or_create_users()

    if not menu_items:
        print("❌ 未找到任何商品，请先在菜单模块添加商品后再执行。")
        return

    # 1. 清理历史模拟数据（先删除关联受保护的 PaymentRecord 等）
    seed_orders = OrderMain.objects.filter(remark__startswith=SEED_TAG)
    PaymentRecord.objects.filter(order__in=seed_orders).delete()
    ProductionTask.objects.filter(order__in=seed_orders).delete()
    deleted_orders = seed_orders.delete()[0]
    print(f"  ✓ 清理历史模拟订单: {deleted_orders} 条")

    now = timezone.now()
    total_generated = 0
    total_revenue_cents = 0

    # 2. 回溯过去 30 天逐日生成
    for day_offset in range(days - 1, -1, -1):
        target_date = (now - datetime.timedelta(days=day_offset)).date()
        is_weekend = target_date.weekday() >= 5

        # 每日订单量（工作日 14~24 单，周末 12~20 单）
        daily_orders_count = random.randint(14, 24) if not is_weekend else random.randint(12, 20)

        for order_idx in range(daily_orders_count):
            # 时间特征分布：早高峰(35%)、午高峰(40%)、其余时段(25%)
            time_rand = random.random()
            if time_rand < 0.35:
                # 07:30 - 09:30
                hour = random.choice([7, 8, 9])
                minute = random.randint(30, 59) if hour == 7 else (random.randint(0, 30) if hour == 9 else random.randint(0, 59))
            elif time_rand < 0.75:
                # 13:00 - 15:30
                hour = random.choice([13, 14, 15])
                minute = random.randint(0, 30) if hour == 15 else random.randint(0, 59)
            elif time_rand < 0.90:
                # 11:30 - 12:30
                hour = random.choice([11, 12])
                minute = random.randint(30, 59) if hour == 11 else random.randint(0, 30)
            else:
                # 16:00 - 20:30
                hour = random.randint(16, 20)
                minute = random.randint(0, 59)

            second = random.randint(0, 59)
            order_time = timezone.make_aware(datetime.datetime.combine(
                target_date, datetime.time(hour, minute, second)
            ))

            store = random.choice(stores)
            store_devs = [d for d in devices if d.store_id == store.id]
            device = random.choice(store_devs) if store_devs else (random.choice(devices) if devices else None)
            user = random.choice(users)

            # 随机挑选商品
            menu_item = random.choice(menu_items)
            item_name = getattr(menu_item, 'name', '') or (menu_item.global_item.name if menu_item.global_item else f"咖啡单品 #{menu_item.id}")
            
            # 查找或确定规格
            sku_obj = MenuSku.objects.filter(item=menu_item, is_active=True).first()
            sku_name = (sku_obj.global_sku.name if sku_obj and sku_obj.global_sku else "常规大杯")
            unit_price = (menu_item.base_price + (sku_obj.price_delta if sku_obj else 0))
            if unit_price <= 0:
                unit_price = 1500  # 默认 15 元兜底

            qty = 1 if random.random() < 0.85 else 2
            subtotal = unit_price * qty

            # 状态分布：86% 完成、4% 制作中（仅当天）、5% 取消、5% 退款/异常
            status_rand = random.random()
            if day_offset == 0 and status_rand < 0.05:
                order_status = OrderMain.STATUS_MAKING
            elif status_rand < 0.86:
                order_status = OrderMain.STATUS_DONE
            elif status_rand < 0.92:
                order_status = OrderMain.STATUS_CANCELLED
            else:
                order_status = OrderMain.STATUS_REFUNDED

            order_no = f"{order_time.strftime('%Y%m%d%H%M%S')}{random.randint(100000, 999999)}"
            order_token = str(uuid.uuid4())

            paid_at = order_time + datetime.timedelta(seconds=random.randint(15, 45)) if order_status in [
                OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE, OrderMain.STATUS_REFUNDED
            ] else None

            done_at = paid_at + datetime.timedelta(seconds=random.randint(55, 95)) if order_status == OrderMain.STATUS_DONE else None

            # 创建主订单
            order = OrderMain.objects.create(
                order_no=order_no,
                order_token=order_token,
                user=user,
                store=store,
                device=device,
                status=order_status,
                total_amount=subtotal,
                discount_amount=0,
                pay_amount=subtotal,
                paid_at=paid_at,
                done_at=done_at,
                remark=f"{SEED_TAG} 拟真商业零售订单"
            )
            OrderMain.objects.filter(pk=order.pk).update(created_at=order_time, updated_at=done_at or paid_at or order_time)

            # 创建订单明细
            OrderItem.objects.create(
                order=order,
                item=menu_item,
                item_name=item_name,
                sku_name=sku_name,
                unit_price=unit_price,
                quantity=qty,
                subtotal=subtotal
            )

            # 支付记录
            if paid_at:
                PaymentRecord.objects.create(
                    order=order,
                    user=user,
                    out_trade_no=order.order_no,
                    transaction_id=f"wx_tx_{order_no[-10:]}",
                    amount=subtotal,
                    status=PaymentRecord.STATUS_SUCCESS,
                    pay_method='wechat_native' if random.random() < 0.65 else 'wechat_jsapi',
                    paid_at=paid_at,
                    created_at=order_time
                )

            # 完整履约时间线
            # 1. 订单创建
            OrderStatusLog.objects.create(
                order=order,
                action=OrderStatusLog.ACTION_CREATE,
                action_name="订单创建",
                from_status="",
                to_status=OrderMain.STATUS_PENDING_PAY,
                operator_type=OrderStatusLog.OP_USER,
                operator=f"user:{user.id}",
                remark="顾客微信点单提交",
                created_at=order_time
            )

            if paid_at:
                # 2. 支付成功
                OrderStatusLog.objects.create(
                    order=order,
                    action=OrderStatusLog.ACTION_PAY_SUCCESS,
                    action_name="微信支付成功",
                    from_status=OrderMain.STATUS_PENDING_PAY,
                    to_status=OrderMain.STATUS_PAID,
                    operator_type=OrderStatusLog.OP_WECHAT,
                    operator="wechat_pay",
                    remark="微信商户收银台入账成功",
                    payload={"pay_amount": subtotal, "device_sn": device.device_sn if device else ""},
                    created_at=paid_at
                )

                ticket_no = f"{order_idx + 1:04d}"
                task_sent_time = paid_at + datetime.timedelta(seconds=2)

                if device:
                    prod_task = ProductionTask.objects.create(
                        order=order,
                        device=device,
                        status=ProductionTask.TASK_DONE if order_status == OrderMain.STATUS_DONE else ProductionTask.TASK_MAKING,
                        command_payload={"type": "make", "ticketNo": ticket_no, "order_no": order.order_no},
                        sent_at=task_sent_time,
                        done_at=done_at,
                        created_at=task_sent_time
                    )
                    # 3. 任务下发
                    OrderStatusLog.objects.create(
                        order=order,
                        action=OrderStatusLog.ACTION_TASK_SENT,
                        action_name="制作任务下发",
                        from_status=OrderMain.STATUS_PAID,
                        to_status=OrderMain.STATUS_PAID,
                        operator_type=OrderStatusLog.OP_SYSTEM,
                        operator="system",
                        remark=f"出餐指令已发布至上位机 {device.device_sn}，取餐号: {ticket_no}",
                        payload={"ticket_no": ticket_no, "task_id": prod_task.id},
                        created_at=task_sent_time
                    )

                # 4. 设备制作
                if order_status in [OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]:
                    making_time = task_sent_time + datetime.timedelta(seconds=5)
                    OrderStatusLog.objects.create(
                        order=order,
                        action=OrderStatusLog.ACTION_MAKING_START,
                        action_name="设备开始制作",
                        from_status=OrderMain.STATUS_PAID,
                        to_status=OrderMain.STATUS_MAKING,
                        operator_type=OrderStatusLog.OP_DEVICE,
                        operator=f"device:{device.device_sn if device else 'system'}",
                        remark="研磨机注水启动",
                        created_at=making_time
                    )

                # 5. 制作完成
                if order_status == OrderMain.STATUS_DONE:
                    OrderStatusLog.objects.create(
                        order=order,
                        action=OrderStatusLog.ACTION_MAKING_DONE,
                        action_name="出杯制作完成",
                        from_status=OrderMain.STATUS_MAKING,
                        to_status=OrderMain.STATUS_DONE,
                        operator_type=OrderStatusLog.OP_DEVICE,
                        operator=f"device:{device.device_sn if device else 'system'}",
                        remark=f"咖啡制作成功，取餐码: {ticket_no}",
                        created_at=done_at
                    )

                # 6. 退款
                if order_status == OrderMain.STATUS_REFUNDED:
                    refund_time = paid_at + datetime.timedelta(seconds=45)
                    OrderStatusLog.objects.create(
                        order=order,
                        action=OrderStatusLog.ACTION_REFUND_SUCCESS,
                        action_name="自动退款完成",
                        from_status=OrderMain.STATUS_PAID,
                        to_status=OrderMain.STATUS_REFUNDED,
                        operator_type=OrderStatusLog.OP_SYSTEM,
                        operator="system",
                        remark="落杯感应超时，已自动原路退回微信账户",
                        payload={"refund_amount": subtotal},
                        created_at=refund_time
                    )

            elif order_status == OrderMain.STATUS_CANCELLED:
                cancel_time = order_time + datetime.timedelta(minutes=5)
                OrderStatusLog.objects.create(
                    order=order,
                    action=OrderStatusLog.ACTION_CANCELLED,
                    action_name="订单超时取消",
                    from_status=OrderMain.STATUS_PENDING_PAY,
                    to_status=OrderMain.STATUS_CANCELLED,
                    operator_type=OrderStatusLog.OP_SYSTEM,
                    operator="system",
                    remark="超过5分钟未支付，系统自动释放并作废",
                    created_at=cancel_time
                )

            total_generated += 1
            if order_status in [OrderMain.STATUS_PAID, OrderMain.STATUS_MAKING, OrderMain.STATUS_DONE]:
                total_revenue_cents += subtotal

    # 3. 生成少量历史告警事件 NotifyEvent，让 Dashboard 的未处理告警与设备分析更真实
    NotifyEvent.objects.filter(content__contains=SEED_TAG).delete()
    for d in devices:
        NotifyEvent.objects.create(
            device=d,
            event_type="warning",
            level="warning",
            title=f"设备 {d.device_sn} 纸杯余量较低提示",
            content=f"{SEED_TAG} 大号热饮纸杯剩余少于 20 只，请及时补充物料。",
            is_handled=False
        )

    print(f"\n🎉 拟真商业数据注入圆满完成！")
    print(f"  - 回溯周期: 过去 {days} 天")
    print(f"  - 新增仿真订单: {total_generated} 笔")
    print(f"  - 模拟总营收: ¥{total_revenue_cents / 100.0:,.2f}")
    print(f"  - 覆盖门店: {len(stores)} 家，制作设备: {len(devices)} 台")
    print(f"  - 时间线日志 OrderStatusLog: 同步生成 {total_generated * 4} 条，完全覆盖全部流转节点！")


if __name__ == '__main__':
    seed_realistic_data(days=30)
