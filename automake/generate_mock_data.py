import os
import django
import random
import datetime
from django.utils import timezone
from decimal import Decimal

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "default.settings")
django.setup()

from users.models import User
from stores.models import Store
from devices.models import Device
from global_config.models import GlobalMenuItem, DeviceModel, GlobalMenuCategory
from menus.models import MenuItem
from orders.models import OrderMain, OrderItem, ProductionTask

def run():
    print("Starting mock data generation...")
    # 1. Create a dummy user
    user, _ = User.objects.get_or_create(username="mock_user", defaults={"phone": "13800138000"})
    print("User ready.")

    # 2. Create a store
    store, _ = Store.objects.get_or_create(name="Mock Store A", defaults={"status": Store.STATUS_OPEN, "contact_phone": "13800138000"})
    print("Store ready.")

    # Create DeviceModel and Category
    dm, _ = DeviceModel.objects.get_or_create(name="Mock Device Model", defaults={"code": "MDM1"})
    category, _ = GlobalMenuCategory.objects.get_or_create(name="Coffee", defaults={"device_model": dm})

    # 3. Create devices
    device_statuses = ['online'] * 8 + ['offline'] * 2 + ['fault'] * 1
    for i, status in enumerate(device_statuses):
        Device.objects.get_or_create(
            device_sn=f"MOCK_DEV_{i+1:03d}",
            defaults={
                "store": store,
                "device_model": dm,
                "device_name": f"Mock Device {i+1}",
                "status": status
            }
        )
    devices = list(Device.objects.filter(store=store))
    print("Devices ready.")

    # 4. Create Menu Items
    drinks = [
        ("经典拿铁", 1800),
        ("美式咖啡", 1200),
        ("焦糖玛奇朵", 2200),
        ("卡布奇诺", 1800),
        ("抹茶拿铁", 2000),
        ("生椰拿铁", 2000),
        ("燕麦拿铁", 2200),
        ("冷萃黑咖", 1600),
        ("乌龙茶", 1000),
        ("红茶玛奇朵", 1500),
    ]

    menu_items = []
    for name, price in drinks:
        g_item, _ = GlobalMenuItem.objects.get_or_create(name=name, defaults={"base_price": price, "category": category})
        m_item, _ = MenuItem.objects.get_or_create(global_item=g_item, store=store, defaults={"base_price": price, "is_active": True, "device_model": dm})
        menu_items.append(m_item)
    print("Menu items ready.")

    # 5. Generate Orders for the last 7 days
    today = timezone.now()

    # Clear existing mock orders
    OrderMain.objects.filter(user=user).delete()

    for i in range(7):
        current_date = today - datetime.timedelta(days=i)
        num_orders = random.randint(15, 45)
        
        for _ in range(num_orders):
            hour = random.randint(8, 20)
            minute = random.randint(0, 59)
            order_time = current_date.replace(hour=hour, minute=minute)
            
            device = random.choice(devices)
            
            order = OrderMain.objects.create(
                user=user,
                store=store,
                device=device,
                status=OrderMain.STATUS_DONE,
                total_amount=0,
                pay_amount=0,
                paid_at=order_time,
                done_at=order_time + datetime.timedelta(minutes=3),
            )
            
            # Bypass auto_now_add
            OrderMain.objects.filter(id=order.id).update(created_at=order_time)
            
            total_amount = 0
            for _ in range(random.randint(1, 3)):
                weights = [10, 8, 5, 5, 7, 12, 6, 4, 3, 2]
                item = random.choices(menu_items, weights=weights)[0]
                quantity = random.randint(1, 2)
                subtotal = item.base_price * quantity
                total_amount += subtotal
                
                OrderItem.objects.create(
                    order=order,
                    item=item,
                    item_name=item.name,
                    unit_price=item.base_price,
                    quantity=quantity,
                    subtotal=subtotal
                )
                
            order.total_amount = total_amount
            order.pay_amount = total_amount
            order.save(update_fields=['total_amount', 'pay_amount'])
            
            task = ProductionTask.objects.create(
                order=order,
                device=device,
                status=ProductionTask.TASK_DONE,
                done_at=order.done_at
            )
            ProductionTask.objects.filter(id=task.id).update(created_at=order_time)

    print("Mock data generated successfully!")

if __name__ == "__main__":
    run()
