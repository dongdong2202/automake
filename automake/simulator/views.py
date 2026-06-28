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
        from global_config.models import DeviceModel, GlobalMenuCategory, GlobalMenuItem, GlobalMenuSku, GlobalSkuIngredient
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
        
        g_sku, _ = GlobalMenuSku.objects.get_or_create(
            item=g_item,
            name='标准拿铁',
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
        
        # 4. 创建对应的 ProductionTask 任务
        payload = {
            'type': 'make',
            'order_no': order_no,
            'order_token': order.order_token,
            'quantity': 1,
            'items': [
                {'item_name': '测试拿铁', 'sku_name': '标准拿铁', 'quantity': 1}
            ],
            'materials': [
                {'code': 'coffee_bean', 'quantity': 15.0},
                {'code': 'fresh_milk', 'quantity': 150.0},
                {'code': 'paperL', 'quantity': 1.0},
                {'code': 'lid', 'quantity': 1.0}
            ]
        }
        
        task = ProductionTask.objects.create(
            order=order,
            device=device,
            status=ProductionTask.TASK_PENDING,
            command_payload=payload
        )
        
        # 5. 调用 issue_make_command 下发指令，通过 MQTT 广播命令，并更改状态为 'sent'
        success = issue_make_command(
            order_no=order_no,
            device_sn=device_sn,
            command_payload=payload
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
            if mat:
                mat_name = mat.name
                mat_type = mat.material_type
                if mat.material_type == Material.TYPE_CONSUMABLE:
                    stock_obj = DeviceConsumableStock.objects.filter(device=device, code=mat).first()
                    db_qty = float(stock_obj.quantity) if stock_obj else 0.0
                else:
                    stock_obj = DeviceMaterialStock.objects.filter(device=device, code=code).first()
                    db_qty = float(stock_obj.current_remaining_height) if stock_obj else 0.0
                    
            # 从 Redis 查询
            redis_stock_key = f"automake:stock:{device_sn}:{code}"
            raw_redis_val = redis_conn.get(redis_stock_key)
            redis_qty = float(raw_redis_val) / 100.0 if raw_redis_val is not None else 0.0
            
            stock_info.append({
                'code': code,
                'name': mat_name,
                'type': '耗材' if mat_type == Material.TYPE_CONSUMABLE else '食材',
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
