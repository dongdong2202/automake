import json
import logging
import time
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.core.cache import cache
from mqtt import get_mqtt_client

logger = logging.getLogger(__name__)

def simulator_view(request):
    """
    渲染上位机通信模拟器的主页面。
    将后端配置的 MQTT 代理服务器连接参数传递给前端展示。
    """
    context = {
        'mqtt_host': getattr(settings, 'MQTT_HOST', '127.0.0.1'),
        'mqtt_port': getattr(settings, 'MQTT_PORT', 1883),
        'mqtt_client_id': getattr(settings, 'MQTT_CLIENT_ID', 'automake_server'),
    }
    # 使用 Django 内置的 render 渲染模板，该模板使用了高级 UI 样式设计
    return render(request, 'simulator/index.html', context)


def simulator_status_api(request):
    """
    获取后端 MQTT 客户端的连接状态。
    """
    device_sn = request.GET.get('sn', '').strip()
    if not device_sn:
        return JsonResponse({'code': 400, 'message': '缺少设备序列号 SN'}, status=400)
    
    try:
        client = get_mqtt_client()
        # paho-mqtt Client 提供了 is_connected() 方法检测底层 Socket 连接状态
        connected = client.is_connected() if client else False
    except Exception as e:
        logger.error(f'获取 MQTT 客户端连接状态异常: {e}')
        connected = False
        
    return JsonResponse({
        'code': 0,
        'message': 'success',
        'data': {
            'mqtt_connected': connected,
            'device_sn': device_sn
        }
    })


def simulator_logs_api(request):
    """
    获取特定设备序列号的模拟器日志记录列表（包含接收到的指令与上报的状态）。
    通过轮询此接口，前端可以实时查看到云端下发的 MQTT 指令。
    """
    device_sn = request.GET.get('sn', '').strip()
    if not device_sn:
        return JsonResponse({'code': 400, 'message': '缺少设备序列号 SN'}, status=400)
        
    # 从缓存中读取该设备的日志列表（之前由 mqtt/__init__.py 中的拦截器存入）
    key = f"simulator:logs:{device_sn}"
    logs = cache.get(key, [])
    
    return JsonResponse({
        'code': 0,
        'message': 'success',
        'data': {
            'logs': logs
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def simulator_report_api(request):
    """
    上位机状态与物料数据上报接口。
    前端页面发出 POST 请求，由后端 Python 服务接收并使用全局 MQTT 客户端发送至代理服务器，
    从而真实模拟硬件上位机的行为，触发云端的业务逻辑处理。
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        return JsonResponse({'code': 400, 'message': f'无效的 JSON 格式: {e}'}, status=400)
        
    device_sn = data.get('device_sn', '').strip()
    topic_type = data.get('topic_type', '').strip()  # 'status' 或 'material'
    payload = data.get('payload')
    
    if not device_sn or not topic_type or payload is None:
        return JsonResponse({'code': 400, 'message': '缺少必要参数 (device_sn, topic_type, payload)'}, status=400)
        
    if topic_type not in ('status', 'material'):
        return JsonResponse({'code': 400, 'message': f'不支持的 topic_type: {topic_type}'}, status=400)
        
    topic = f'automake/device/{device_sn}/{topic_type}'
    
    try:
        # 获取全局 MQTT 客户端实例并进行消息发布
        client = get_mqtt_client()
        if not client or not client.is_connected():
            return JsonResponse({'code': 500, 'message': '后端 MQTT 客户端未连接，无法发布消息'}, status=500)
            
        # 将 payload 转为 JSON 字符串发布至对应的 MQTT 主题
        payload_str = json.dumps(payload, ensure_ascii=False)
        result = client.publish(topic, payload_str, qos=1)
        
        # paho-mqtt publish 会返回一个 publish result, rc == 0 代表发布成功
        if result.rc != 0:
            logger.error(f'后端 MQTT 发布消息失败, topic={topic}, rc={result.rc}')
            return JsonResponse({'code': 500, 'message': f'MQTT 发布消息失败, 返回码: {result.rc}'}, status=500)
            
        # 消息发送成功后，将此发送记录作为 "sent" 类型的日志写入该设备的 Redis 缓存中，供前端轮询时一并获取
        key = f"simulator:logs:{device_sn}"
        logs = cache.get(key, [])
        logs.append({
            "timestamp": time.time(),
            "type": "sent",
            "topic": topic,
            "payload": payload
        })
        if len(logs) > 100:
            logs = logs[-100:]
        cache.set(key, logs, timeout=86400)
        
        logger.info(f"[SIMULATOR] 后端成功发布上报消息: device_sn={device_sn}, topic={topic}")
        return JsonResponse({'code': 0, 'message': 'success'})
        
    except Exception as e:
        logger.exception(f'模拟上报接口内部错误: {e}')
        return JsonResponse({'code': 500, 'message': f'上报消息发生异常: {e}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def simulator_clear_logs_api(request):
    """
    清空特定设备的模拟器日志记录。
    """
    device_sn = request.GET.get('sn', '').strip()
    if not device_sn:
        return JsonResponse({'code': 400, 'message': '缺少设备序列号 SN'}, status=400)
        
    key = f"simulator:logs:{device_sn}"
    cache.delete(key)
    return JsonResponse({'code': 0, 'message': 'success'})


@csrf_exempt
@require_http_methods(["POST"])
def simulator_create_test_order_api(request):
    """
    一键创建虚拟成功业务流程的测试订单。
    
    1. 确保或创建测试门店、测试设备，并在线和绑定设备。
    2. 初始化该设备在数据库（DeviceConsumableStock, DeviceMaterialStock）和 Redis 中的耗材与原材料库存为 100.00。
    3. 确保本地商品 "测试拿铁" 及其配方（包含 coffee_bean, fresh_milk, paperL, lid）存在。
    4. 创建状态为 PENDING_DISPENSE (等候出货) 的 OrderMain 和对应的 ProductionTask。
    5. 调用 issue_make_command 下发 MQTT 制作命令。
    """
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        data = {}
        
    device_sn = data.get('device_sn', 'SN001').strip()
    if not device_sn:
        device_sn = 'SN001'
        
    try:
        from stores.models import Store
        from devices.models import Device, DeviceConsumableStock, DeviceMaterialStock
        from inventory.models import Material
        from menus.models import MenuItem, MenuSku
        from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
        from orders.models import OrderMain, OrderItem, ProductionTask
        from mqtt import issue_make_command
        from orders.services import get_consumable_name_by_code
        from django_redis import get_redis_connection
        from django.utils import timezone
        from decimal import Decimal
        import uuid
        
        # 1. 确保并初始化门店和设备
        store, _ = Store.objects.get_or_create(
            code='first1',
            defaults={
                'name': '西二旗智能咖啡店',
                'address': '北京市海淀区西二旗软件园',
                'contact_phone': '13812345678',
                'status': Store.STATUS_OPEN
            }
        )
        
        dev_type, _ = DeviceModel.objects.get_or_create(
            code='coffee_maker',
            defaults={
                'name': '智能咖啡机',
                'description': '支持咖啡制作的设备类型'
            }
        )
        
        device, _ = Device.objects.get_or_create(
            device_sn=device_sn,
            defaults={
                'store': store,
                'device_name': f'测试设备 {device_sn}',
                'status': Device.STATUS_ONLINE,
                'key_code': 'first1',
                'device_model': dev_type
            }
        )
        
        # 确保设备是 online 状态，且绑定了门店
        device.status = Device.STATUS_ONLINE
        device.store = store
        device.key_code = 'first1'
        device.device_model = dev_type
        device.save()
        
        # 2. 确保商品、SKU 极其原料配方关联
        g_category, _ = GlobalMenuCategory.objects.get_or_create(
            device_model=dev_type,
            name='经典咖啡',
            defaults={'sort_order': 1, 'is_active': True}
        )
        
        g_item, _ = GlobalMenuItem.objects.get_or_create(
            category=g_category,
            name='测试拿铁',
            defaults={'description': '模拟器专属测试拿铁', 'base_price': 1800, 'is_active': True}
        )
        
        tpl_latte, _ = GlobalSkuTemplate.objects.get_or_create(
            name='标准拿铁',
            category='默认',
            defaults={'default_price_delta': 0, 'is_active': True}
        )

        g_sku, _ = GlobalMenuSku.objects.get_or_create(
            item=g_item,
            template=tpl_latte,
            defaults={'price_delta': 0, 'is_active': True}
        )
        
        item_local, _ = MenuItem.objects.get_or_create(
            store=store,
            device_model=dev_type,
            global_item=g_item,
            defaults={'base_price': 1800, 'is_active': True}
        )
        
        sku_local, _ = MenuSku.objects.get_or_create(
            item=item_local,
            global_sku=g_sku,
            defaults={'price_delta': 0, 'is_active': True}
        )
        
        # 确保物料及其配方关联
        materials_setup = [
            {'code': 'coffee_bean', 'name': '咖啡豆', 'type': Material.TYPE_INGREDIENT, 'unit': 'g', 'qty': Decimal('15.00')},
            {'code': 'fresh_milk', 'name': '鲜牛奶', 'type': Material.TYPE_INGREDIENT, 'unit': 'ml', 'qty': Decimal('150.00')},
            {'code': 'paperL', 'name': get_consumable_name_by_code('paperL'), 'type': Material.TYPE_CONSUMABLE, 'unit': '个', 'qty': Decimal('1.00')},
            {'code': 'lid', 'name': get_consumable_name_by_code('lid'), 'type': Material.TYPE_CONSUMABLE, 'unit': '个', 'qty': Decimal('1.00')},
        ]
        
        redis_conn = get_redis_connection("default")
        
        for item in materials_setup:
            mat, _ = Material.objects.get_or_create(
                code=item['code'],
                defaults={
                    'name': item['name'],
                    'material_type': item['type'],
                    'unit': item['unit'],
                    'shelf_life': '永久',
                    'storage_conditions': '常温'
                }
            )
            if mat.material_type != item['type']:
                mat.material_type = item['type']
                mat.save()
                
            # 确保配料存在
            GlobalSkuIngredient.objects.get_or_create(
                sku=g_sku,
                material=mat,
                defaults={'quantity': item['qty']}
            )
            
            # 初始化该设备下的数据库库存为 100
            if item['type'] == Material.TYPE_CONSUMABLE:
                DeviceConsumableStock.objects.update_or_create(
                    device=device,
                    code=mat,
                    defaults={'init_quantity': 100, 'quantity': 100, 'unit': item['unit'], 'warn_level': 20}
                )
            else:
                DeviceMaterialStock.objects.update_or_create(
                    device=device,
                    code=item['code'],
                    defaults={'name': mat, 'unit': item['unit'], 'warn_level': 10.00, 'current_remaining_height': Decimal('100.00')}
                )
                
            # 重置 Redis 库存（放大 100 倍存储以支持 Decimal 转换，即 100.00 = 10000）
            redis_stock_key = f"automake:stock:{device_sn}:{item['code']}"
            redis_conn.set(redis_stock_key, 10000)
            
        # 3. 创建测试订单
        order_no = 'TEST-' + timezone.now().strftime('%Y%m%d%H%M%S') + str(uuid.uuid4().hex[:4]).upper()
        
        from users.models import User
        user, _ = User.objects.get_or_create(
            openid='dev-test-openid',
            defaults={'username': 'dev_tester', 'role': User.CUSTOMER, 'is_active': True}
        )
        
        order = OrderMain.objects.create(
            order_no=order_no,
            store=store,
            user=user,
            device=device,
            status=OrderMain.STATUS_PAID, # 'pending_dispense'
            total_amount=1800,
            discount_amount=0,
            pay_amount=1800,
            order_token=str(uuid.uuid4())
        )
        
        order_item = OrderItem.objects.create(
            order=order,
            item=item_local,
            sku=sku_local,
            item_name='测试拿铁',
            sku_name='标准拿铁',
            unit_price=1800,
            quantity=1,
            subtotal=1800
        )
        order_item.skus.add(sku_local)
        
        # 4. 创建对应的 ProductionTask 任务（统一使用 create_production_task 生成标准化 Payload）
        from orders.services import create_production_task
        task = create_production_task(order)
        
        # 5. 调用 issue_make_command 下发指令，通过 MQTT 广播命令，并更改状态为 'sent'
        success = issue_make_command(
            order_no=order_no,
            device_sn=device_sn,
            command_payload=task.command_payload
        )
        
        if not success:
            return JsonResponse({'code': 500, 'message': '创建订单成功，但下发 MQTT 制作指令失败'}, status=500)
            
        logger.info(f"[SIMULATOR] 一键初始化测试订单成功: order_no={order_no}, device_sn={device_sn}")
        return JsonResponse({
            'code': 0,
            'message': 'success',
            'data': {
                'order_no': order_no,
                'device_sn': device_sn
            }
        })
        
    except Exception as e:
        logger.exception(f'一键创建测试订单异常: {e}')
        return JsonResponse({'code': 500, 'message': f'一键创建测试订单异常: {e}'}, status=500)


def simulator_diagnostics_api(request):
    """
    状态诊断接口。返回设备在数据库和 Redis 中的实时数据变化，
    包括最新的订单状态、ProductionTask 状态，以及原材料和耗材的 DB/Redis 库存值。
    """
    device_sn = request.GET.get('sn', '').strip()
    if not device_sn:
        return JsonResponse({'code': 400, 'message': '缺少设备序列号 SN'}, status=400)
        
    try:
        from stores.models import Store
        from devices.models import Device, DeviceConsumableStock, DeviceMaterialStock
        from inventory.models import Material
        from orders.models import OrderMain, ProductionTask
        from django_redis import get_redis_connection
        
        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return JsonResponse({
                'code': 0,
                'message': '设备未在系统中录入',
                'data': {'device_exists': False}
            })
            
        # 1. 查询最新的订单及其状态
        latest_order = OrderMain.objects.filter(device=device).order_by('-created_at').first()
        order_info = None
        if latest_order:
            task = ProductionTask.objects.filter(order=latest_order).first()
            order_info = {
                'order_no': latest_order.order_no,
                'status': latest_order.status,
                'status_display': latest_order.get_status_display(),
                'task_status': task.status if task else None,
                'created_at': latest_order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'done_at': latest_order.done_at.strftime('%Y-%m-%d %H:%M:%S') if latest_order.done_at else '-'
            }
            
        # 2. 查询耗材和食材库存指标 (DB vs Redis)
        redis_conn = get_redis_connection("default")
        materials_monitored = ['coffee_bean', 'fresh_milk', 'paperL', 'lid']
        stock_info = []
        
        for code in materials_monitored:
            db_qty = 0.0
            mat_name = ""
            mat_type = ""
            mat = Material.objects.filter(code=code).first()
            is_consumable = (code in ['paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane']) or (mat and mat.material_type in (Material.TYPE_CONSUMABLE, Material.TYPE_CUP, 'cup', 'consumable'))
            if mat:
                mat_name = mat.name
                mat_type = mat.material_type
                if is_consumable:
                    stock_obj = DeviceConsumableStock.objects.filter(device=device, code=mat).first()
                    db_qty = float(stock_obj.quantity) if stock_obj else 0.0
                else:
                    stock_obj = DeviceMaterialStock.objects.filter(device=device, code=code).first()
                    db_qty = float(stock_obj.current_remaining_height) if stock_obj else 0.0
            elif is_consumable:
                stock_obj = DeviceConsumableStock.objects.filter(device=device, code__code=code).first()
                db_qty = float(stock_obj.quantity) if stock_obj else 0.0

            # 从 Redis 查询
            redis_stock_key = f"automake:stock:{device_sn}:{code}"
            raw_redis_val = redis_conn.get(redis_stock_key)
            try:
                redis_qty = float(raw_redis_val) if raw_redis_val is not None else 0.0
            except (ValueError, TypeError):
                redis_qty = 0.0
            
            stock_info.append({
                'code': code,
                'name': mat_name or code,
                'type': '耗材' if is_consumable else '食材',
                'db_qty': db_qty,
                'redis_qty': redis_qty
            })
            
        return JsonResponse({
            'code': 0,
            'message': 'success',
            'data': {
                'device_exists': True,
                'device_name': device.device_name,
                'device_status': device.status,
                'latest_order': order_info,
                'stocks': stock_info
            }
        })
        
    except Exception as e:
        logger.exception(f'获取状态诊断数据异常: {e}')
        return JsonResponse({'code': 500, 'message': f'获取状态诊断异常: {e}'}, status=500)


def simulator_kiosk_view(request):
    """
    渲染上位机触控终端 (Kiosk) 模拟界面。
    默认设备: sn001, 注册码: sn001, 关联门店: 北京1店 (100000)
    """
    context = {
        'device_sn': 'sn001',
        'key_code': 'sn001',
        'store_id': 100000,
        'store_name': '北京1店',
    }
    return render(request, 'simulator/kiosk.html', context)


@csrf_exempt
def simulator_seed_kiosk_menu_api(request):
    """
    一键初始化 0.2 元以内的模拟菜单及 sn001 上位机基础库存。
    商品价格严格控制在 0.20 元以内（如 0.01元、0.10元、0.20元），以供微信支付小额真实测试。
    """
    try:
        from decimal import Decimal
        from stores.models import Store
        from devices.models import Device, DeviceConsumableStock
        from global_config.models import GlobalMenuCategory, GlobalMenuItem, GlobalSkuTemplate, GlobalMenuSku, GlobalSkuIngredient
        from inventory.models import Material
        from menus.models import MenuItem
        from django_redis import get_redis_connection

        device = Device.objects.filter(device_sn='sn001').first()
        if not device:
            return JsonResponse({'code': 404, 'message': '设备 sn001 不存在，请先录入设备'}, status=404)
        store = device.store
        if not store:
            return JsonResponse({'code': 404, 'message': '设备 sn001 未绑定门店'}, status=404)

        if not store.is_open:
            store.status = Store.STATUS_OPEN
            store.save(update_fields=['status'])

        # 1. 确保基础物料库存在
        mats_config = [
            ('paperL', '纸大杯', Material.TYPE_CONSUMABLE, '个'),
            ('paperM', '纸中杯', Material.TYPE_CONSUMABLE, '个'),
            ('plasticL', '塑料大杯', Material.TYPE_CONSUMABLE, '个'),
            ('plasticM', '塑料中杯', Material.TYPE_CONSUMABLE, '个'),
            ('lid', '杯盖', Material.TYPE_CONSUMABLE, '个'),
            ('membrane', '封口膜', Material.TYPE_CONSUMABLE, '张'),
            ('coffee_bean', '咖啡豆', Material.TYPE_SOLID, 'g'),
            ('fresh_milk', '鲜牛奶', Material.TYPE_THIN, 'ml'),
            ('orange_juice', '鲜橙原汁', Material.TYPE_THIN, 'ml'),
            ('water', '纯净水', Material.TYPE_THIN, 'ml'),
        ]
        materials = {}
        for code, name, m_type, unit in mats_config:
            mat = Material.objects.filter(code=code).first()
            if not mat:
                mat = Material.objects.filter(name=name).first()
                if not mat:
                    mat = Material.objects.create(code=code, name=name, material_type=m_type, unit=unit, quantity=9999)
                else:
                    if not mat.code:
                        mat.code = code
                        mat.save(update_fields=['code'])
            materials[code] = mat

        # 2. 确保 sn001 设备耗材库存充足
        consumable_codes = ['paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane']
        for code in consumable_codes:
            mat = materials.get(code)
            if mat:
                cs, _ = DeviceConsumableStock.objects.get_or_create(
                    device=device,
                    code=mat,
                    defaults={'quantity': 100}
                )
                if cs.quantity < 50:
                    cs.quantity = 100
                    cs.save(update_fields=['quantity'])

        # 3. 确保 Redis 原料与耗材库存充足
        redis_conn = get_redis_connection('default')
        redis_stocks = {
            'paperL': 100, 'paperM': 100, 'plasticL': 100, 'plasticM': 100,
            'lid': 100, 'membrane': 100, 'water': 5000,
            'coffee_bean': 1000, 'fresh_milk': 2000, 'orange_juice': 3000,
        }
        for code, val in redis_stocks.items():
            redis_conn.set(f'automake:stock:sn001:{code}', val)

        # 4. 规格模板（价格增量均为 0，确保单杯价格不超过 0.20 元）
        tpl_cup_big, _ = GlobalSkuTemplate.objects.get_or_create(name='大杯', category='杯型', defaults={'default_price_delta': 0})
        tpl_cup_small, _ = GlobalSkuTemplate.objects.get_or_create(name='小杯', category='杯型', defaults={'default_price_delta': 0})
        tpl_hot, _ = GlobalSkuTemplate.objects.get_or_create(name='热', category='温度', defaults={'default_price_delta': 0})
        tpl_cold, _ = GlobalSkuTemplate.objects.get_or_create(name='冷', category='温度', defaults={'default_price_delta': 0})
        tpl_normal, _ = GlobalSkuTemplate.objects.get_or_create(name='常温', category='温度', defaults={'default_price_delta': 0})

        cat_coffee = GlobalMenuCategory.objects.filter(name='咖啡', device_model=device.device_model).first() or GlobalMenuCategory.objects.filter(name='咖啡').first()
        cat_juice = GlobalMenuCategory.objects.filter(name='果汁', device_model=device.device_model).first() or GlobalMenuCategory.objects.filter(name='果汁').first()

        # 5. 创建 3 款价格 <= 0.20 元的模拟商品
        # 商品 1: 浓缩咖啡 (1分钱, ¥0.01)
        item_espresso, _ = GlobalMenuItem.objects.get_or_create(
            category=cat_coffee,
            name='浓缩咖啡(测试0.01元)',
            defaults={
                'base_price': 1,
                'description': '上位机测试专享·浓缩意式咖啡 (0.01元)',
                'main_ingredients': '精选咖啡豆 15g',
                'price_description': '实付 0.01 元',
                'is_active': True,
                'sort_order': 1
            }
        )
        item_espresso.base_price = 1
        item_espresso.save()

        # 商品 2: 经典拿铁 (1毛钱, ¥0.10)
        item_latte, _ = GlobalMenuItem.objects.get_or_create(
            category=cat_coffee,
            name='经典拿铁(测试0.10元)',
            defaults={
                'base_price': 10,
                'description': '上位机测试专享·新鲜奶泡拿铁 (0.10元)',
                'main_ingredients': '精选咖啡豆 15g + 优质鲜奶 150ml',
                'price_description': '实付 0.10 元',
                'is_active': True,
                'sort_order': 2
            }
        )
        item_latte.base_price = 10
        item_latte.save()

        # 商品 3: 鲜榨橙汁 (2毛钱, ¥0.20)
        item_juice, _ = GlobalMenuItem.objects.get_or_create(
            category=cat_juice,
            name='鲜榨橙汁(测试0.20元)',
            defaults={
                'base_price': 20,
                'description': '上位机测试专享·VC鲜榨鲜橙汁 (0.20元)',
                'main_ingredients': '鲜橙原汁 200ml',
                'price_description': '实付 0.20 元',
                'is_active': True,
                'sort_order': 3
            }
        )
        item_juice.base_price = 20
        item_juice.save()

        # 关联 SKU 与配料 (delta 均为 0)
        for tpl in [tpl_cup_big, tpl_cup_small, tpl_hot, tpl_normal]:
            sku, _ = GlobalMenuSku.objects.get_or_create(item=item_espresso, template=tpl, defaults={'price_delta': 0})
            sku.price_delta = 0
            sku.save()
            GlobalSkuIngredient.objects.get_or_create(sku=sku, material=materials['coffee_bean'], defaults={'quantity': Decimal('15.00'), 'unit': 'g'})

        for tpl in [tpl_cup_big, tpl_cup_small, tpl_hot, tpl_cold]:
            sku, _ = GlobalMenuSku.objects.get_or_create(item=item_latte, template=tpl, defaults={'price_delta': 0})
            sku.price_delta = 0
            sku.save()
            GlobalSkuIngredient.objects.get_or_create(sku=sku, material=materials['coffee_bean'], defaults={'quantity': Decimal('15.00'), 'unit': 'g'})
            GlobalSkuIngredient.objects.get_or_create(sku=sku, material=materials['fresh_milk'], defaults={'quantity': Decimal('150.00'), 'unit': 'ml'})

        for tpl in [tpl_cup_big, tpl_cup_small, tpl_cold, tpl_normal]:
            sku, _ = GlobalMenuSku.objects.get_or_create(item=item_juice, template=tpl, defaults={'price_delta': 0})
            sku.price_delta = 0
            sku.save()
            GlobalSkuIngredient.objects.get_or_create(sku=sku, material=materials['orange_juice'], defaults={'quantity': Decimal('200.00'), 'unit': 'ml'})

        # 6. 同步至当前门店
        MenuItem.sync_store_menu(store)

        return JsonResponse({
            'code': 0,
            'message': '0.2元内模拟测试菜单及库存已成功初始化！',
            'data': {
                'items': [
                    {'name': '浓缩咖啡(测试0.01元)', 'price_fen': 1, 'price_yuan': 0.01},
                    {'name': '经典拿铁(测试0.10元)', 'price_fen': 10, 'price_yuan': 0.10},
                    {'name': '鲜榨橙汁(测试0.20元)', 'price_fen': 20, 'price_yuan': 0.20},
                ],
                'stock_status': '所有物料与耗材已补齐 (100+)'
            }
        })
    except Exception as e:
        logger.exception(f'初始化上位机菜单异常: {e}')
        return JsonResponse({'code': 500, 'message': f'初始化模拟菜单异常: {e}'}, status=500)


@csrf_exempt
def simulator_toggle_kiosk_stock_api(request):
    """
    一键调节上位机库存余量（供测试库存拦截与放行）。
    支持清空纸杯/杯盖/原料（模拟售罄拦截），或一键补满（恢复放行）。
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body.decode('utf-8'))
            except Exception:
                pass
        device_sn = data.get('device_sn') or request.GET.get('device_sn') or 'sn001'
        material_code = data.get('material_code') or request.GET.get('material_code') or 'paperL'
        action = data.get('action') or request.GET.get('action') or ''
        quantity = data.get('quantity') if 'quantity' in data else request.GET.get('quantity')

        from devices.models import Device, DeviceConsumableStock
        from inventory.models import Material
        from django_redis import get_redis_connection

        device = Device.objects.filter(device_sn=device_sn).first()
        if not device:
            return JsonResponse({'code': 404, 'message': f'设备 {device_sn} 不存在'}, status=404)

        redis_conn = get_redis_connection('default')

        if action == 'empty' or str(quantity) == '0':
            # 清空指定物料 (默认 paperL 纸杯)
            mat = Material.objects.filter(code=material_code).first()
            if mat and mat.material_type in (Material.TYPE_CONSUMABLE, Material.TYPE_CUP):
                cs = DeviceConsumableStock.objects.filter(device=device, code=mat).first()
                if cs:
                    cs.quantity = 0
                    cs.save(update_fields=['quantity', 'updated_at'])
            redis_conn.set(f'automake:stock:{device_sn}:{material_code}', 0)
            msg = f'已成功清空物料 【{material_code}】（库存设为 0），现在下单将触发缺货拦截报错'
        else:
            # 补满全部物料 (100 / 1000)
            consumable_codes = ['paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane']
            for c in consumable_codes:
                mat = Material.objects.filter(code=c).first()
                if mat:
                    cs, _ = DeviceConsumableStock.objects.get_or_create(
                        device=device, code=mat, defaults={'quantity': 100}
                    )
                    cs.quantity = 100
                    cs.save(update_fields=['quantity', 'updated_at'])
                redis_conn.set(f'automake:stock:{device_sn}:{c}', 100)

            ingredient_defaults = {
                'coffee_bean': 1000,
                'fresh_milk': 2000,
                'orange_juice': 3000,
                'water': 5000,
            }
            for c, val in ingredient_defaults.items():
                redis_conn.set(f'automake:stock:{device_sn}:{c}', val)
            msg = '已成功补满所有物料与耗材（纸杯、杯盖、咖啡豆、牛奶等均 >= 100），库存校验恢复放行'

        return JsonResponse({'code': 0, 'message': msg})
    except Exception as e:
        logger.exception(f'库存调节异常: {e}')
        return JsonResponse({'code': 500, 'message': f'库存调节异常: {e}'}, status=500)
