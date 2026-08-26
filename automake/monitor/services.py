"""
monitor/services.py —— 设备状态解析、多料桶聚合、实时监控与报警服务
"""

import json
import logging
from decimal import Decimal
from django.utils import timezone
from django_redis import get_redis_connection

from devices.models import Device, DeviceBarrelDict, DeviceMaterialStock, DeviceConsumableStock, DeviceStatusLog, DeviceAlarm
from monitor.models import DeviceMonitorSnapshot
from notifications.services import send_sms_notify, NotifyEvent

logger = logging.getLogger('monitor')

CUP_KEYS = ('plasticL', 'plasticM', 'paperL', 'paperM', 'membrane', 'lid')
BARREL_SECTIONS = ('thinP', 'thickP', 'solidP')


def parse_device_status_payload(device_sn: str, raw_data: dict) -> dict:
    """
    按照 monitor/e.md 规范解析上位机上报的 JSON 数据，并结合 DeviceBarrelDict 进行多料桶物料聚合。
    
    :param device_sn: 设备序列号
    :param raw_data: 上位机上报的原始字典（或包含 data 键的报文）
    :return: 结构化解析结果字典
    """
    if not isinstance(raw_data, dict):
        raw_data = {}
        
    # 兼容报文中顶层嵌套 "data" 字段的情况
    payload = raw_data.get('data') if isinstance(raw_data.get('data'), dict) else raw_data

    # 1. 基础字段解析
    raw_healthy = payload.get('healthy', 1)
    healthy_flag = True if raw_healthy in (1, True, '1', 'true') else False

    raw_disconnected = payload.get('disconnected', 0)
    disconnected_flag = True if raw_disconnected in (1, True, '1', 'true') else False

    free_mem = payload.get('free', {'master': 0, 'slave': 0})
    temperature = payload.get('temperature', {'t1': 0, 't2': 0})
    ice_data = payload.get('ice', {'a1': 0, 'a2': 0, 'a3': 0})
    transfer_data = payload.get('transfer', {'a1': 0})
    cup_data = payload.get('cup', {})
    press_data = payload.get('press', {'a1': 0})
    heat_data = payload.get('heat', {'a1': 0, 'a2': 0, 'a3': 0})
    arm_data = payload.get('arm', {'a1': 0})
    take_data = payload.get('take', {'a1': 0, 'a2': 0, 'a3': 0})
    spray_data = payload.get('spray', {'a1': 0})
    ticket_data = payload.get('ticket', {'a1': 0, 'a2': 0, 'a3': 0, 'a4': 0, 'a5': 0})

    # 2. 读取 DeviceBarrelDict 料桶字典，建立 bXX -> material_code 映射
    barrel_mappings = DeviceBarrelDict.objects.filter(
        device__device_sn=device_sn
    ).select_related('material')

    barrel_to_mat_code = {}
    barrel_to_mat_name = {}
    mat_code_to_name = {}
    
    for item in barrel_mappings:
        if item.material:
            barrel_to_mat_code[item.barrel_code] = item.material.code
            barrel_to_mat_name[item.barrel_code] = item.material.name
            mat_code_to_name[item.material.code] = item.material.name

    # 3. 遍历薄料区(thinP)、厚料区(thickP)、固料区(solidP)，进行料桶解析与多桶余量聚合
    barrel_details = {}
    aggregated_materials = {}
    abnormalities = {}

    for section in BARREL_SECTIONS:
        section_data = payload.get(section, {})
        if not isinstance(section_data, dict):
            continue
            
        for b_code, b_info in section_data.items():
            if not isinstance(b_info, dict):
                continue
                
            v_val = b_info.get('v', 0)
            try:
                v_num = int(v_val)
            except (ValueError, TypeError):
                v_num = 0
                
            a1_val = b_info.get('a1', 0)
            damaged = (a1_val == 1 or a1_val is True)

            mat_code = barrel_to_mat_code.get(b_code)
            mat_name = barrel_to_mat_name.get(b_code, b_code)

            barrel_details[b_code] = {
                'barrel_code': b_code,
                'section': section,
                'volume': v_num,
                'damaged': damaged,
                'material_code': mat_code,
                'material_name': mat_name,
            }

            if damaged:
                abnormalities[f"{section}.{b_code}.a1"] = f"料桶 {b_code}({mat_name}) 模块损坏"

            # 相同 code 物料聚合累加
            if mat_code:
                if mat_code not in aggregated_materials:
                    aggregated_materials[mat_code] = {
                        'code': mat_code,
                        'name': mat_name,
                        'total_volume': 0,
                        'barrels': [],
                        'has_available_barrel': False,
                        'is_low': False,
                        'is_empty': False,
                    }
                aggregated_materials[mat_code]['total_volume'] += v_num
                aggregated_materials[mat_code]['barrels'].append({
                    'barrel_code': b_code,
                    'volume': v_num,
                    'damaged': damaged
                })
                if not damaged and v_num > 0:
                    aggregated_materials[mat_code]['has_available_barrel'] = True

    # 4. 获取物料库存预警配置 (DeviceMaterialStock)
    material_stock_configs = {
        s.code: s for s in DeviceMaterialStock.objects.filter(device__device_sn=device_sn)
    }

    for mat_code, mat_info in aggregated_materials.items():
        stock_cfg = material_stock_configs.get(mat_code)
        # 某种物料累计少于 1000ml 则系统报警
        warn_level = max(float(stock_cfg.warn_level), 1000.0) if stock_cfg else 1000.0
        mat_unit = getattr(stock_cfg, 'unit', '') or ('g' if '粉' in mat_info['name'] or '豆' in mat_info['name'] else 'ml')
        
        if mat_info['total_volume'] <= 0:
            mat_info['is_empty'] = True
            abnormalities[f"material.{mat_code}.empty"] = f"物料 {mat_info['name']}({mat_code}) 已耗尽"
        elif mat_info['total_volume'] < warn_level:
            mat_info['is_low'] = True
            abnormalities[f"material.{mat_code}.low"] = f"物料 {mat_info['name']}({mat_code}) 余量低({mat_info['total_volume']}{mat_unit} < {warn_level}{mat_unit})"

    # 5. 解析杯盖膜 (cup) 状态
    parsed_cups = {}
    for c_key in CUP_KEYS:
        c_info = cup_data.get(c_key, {})
        if isinstance(c_info, dict):
            c_a1 = c_info.get('a1', 0)
            c_a2 = c_info.get('a2', 0)
            is_dmg = (c_a1 == 1 or c_a1 is True)
            is_empty = (c_a2 == 1 or c_a2 is True)
            
            parsed_cups[c_key] = {
                'code': c_key,
                'damaged': is_dmg,
                'empty': is_empty
            }
            if is_dmg:
                abnormalities[f"cup.{c_key}.a1"] = f"耗材 {c_key} 模块损坏"
            if is_empty:
                abnormalities[f"cup.{c_key}.a2"] = f"耗材 {c_key} 已用尽"
        else:
            parsed_cups[c_key] = {'code': c_key, 'damaged': False, 'empty': False}

    # 6. 解析其他硬件模块异常
    if disconnected_flag:
        abnormalities['disconnected'] = "设备已断线/离线"
    if not healthy_flag:
        abnormalities['healthy'] = "设备整机健康状态为异常"

    if ice_data.get('a1') == 1: abnormalities['ice.a1'] = "制冰模块出口区域异常"
    if ice_data.get('a2') == 1: abnormalities['ice.a2'] = "制冰区域异常"
    if ice_data.get('a3') == 1: abnormalities['ice.a3'] = "制冰模块容器缺冰"

    if transfer_data.get('a1') == 1: abnormalities['transfer.a1'] = "转运模块损坏"
    if press_data.get('a1') == 1: abnormalities['press.a1'] = "压盖模块损坏"

    if heat_data.get('a1') == 1: abnormalities['heat.a1'] = "加热水模块损坏"
    if heat_data.get('a2') == 1: abnormalities['heat.a2'] = "加热奶模块损坏"
    if heat_data.get('a3') == 1: abnormalities['heat.a3'] = "加热茶模块损坏"

    if arm_data.get('a1') == 1: abnormalities['arm.a1'] = "机械臂模块损坏"

    if take_data.get('a1') == 1: abnormalities['take.a1'] = "取餐模块一区损坏"
    if take_data.get('a2') == 1: abnormalities['take.a2'] = "取餐模块二区损坏"
    if take_data.get('a3') == 1: abnormalities['take.a3'] = "取餐模块三区损坏"

    if spray_data.get('a1') == 1: abnormalities['spray.a1'] = "喷码模块损坏"

    if ticket_data.get('a1') == 1: abnormalities['ticket.a1'] = "小票打印机掉线"
    if ticket_data.get('a2') == 1: abnormalities['ticket.a2'] = "小票打印机缺纸"
    if ticket_data.get('a3') == 1: abnormalities['ticket.a3'] = "小票打印机过热"
    if ticket_data.get('a4') == 1: abnormalities['ticket.a4'] = "小票打印机切刀出错"
    if ticket_data.get('a5') == 1: abnormalities['ticket.a5'] = "小票打印机未知错误"

    # 7. 综合健康判定（硬件健康度与缺料预警解耦）
    # 硬件部件损坏列表（排除物料低/缺料/缺杯等耗材类预警）
    hardware_fault_keys = [
        k for k in abnormalities 
        if not k.endswith('.empty') and not k.endswith('.low') and not k.endswith('.a2')
    ]
    # 只要没有硬件损坏且上位机 healthy 标志正常，设备硬件即为健康
    is_hardware_healthy = bool(healthy_flag) and (len(hardware_fault_keys) == 0)
    is_healthy = is_hardware_healthy  # 缺料报警不把设备标记为硬件不健康

    if disconnected_flag:
        display_status = 'fault'
    elif not is_hardware_healthy:
        display_status = 'fault'
    elif len(abnormalities) > 0:
        # 仅有缺料/低余量/缺杯时，显示为 warning 预警，报警与短信照常触发，但不置为 offline/fault
        display_status = 'warning'
    else:
        display_status = 'normal'

    now_iso = timezone.now().isoformat()

    return {
        'device_sn': device_sn,
        'healthy': is_healthy,
        'disconnected': disconnected_flag,
        'display_status': display_status,
        'free': free_mem,
        'temperature': temperature,
        'ice': ice_data,
        'transfer': transfer_data,
        'press': press_data,
        'heat': heat_data,
        'arm': arm_data,
        'take': take_data,
        'spray': spray_data,
        'ticket': ticket_data,
        'cups': parsed_cups,
        'barrels': barrel_details,
        'materials': aggregated_materials,
        'abnormalities': abnormalities,
        'reported_at': now_iso,
        'raw_data': payload,
    }


def update_device_status_to_redis(device_sn: str, parsed_data: dict) -> None:
    """
    将解析好的结构化状态及物料可用库存写入 Redis。
    """
    try:
        redis_conn = get_redis_connection("default")
        
        # 1. 写入每种聚合后物料的可用库存量
        # 键名规范：automake:stock:{device_sn}:{material_code}
        for mat_code, mat_info in parsed_data.get('materials', {}).items():
            stock_key = f"automake:stock:{device_sn}:{mat_code}"
            redis_conn.set(stock_key, int(mat_info['total_volume']))

        # 2. 写入耗材可用状态（若用尽则设为 0，若正常且原来没有则设为默认可用）
        for cup_code, cup_info in parsed_data.get('cups', {}).items():
            cup_stock_key = f"automake:stock:{device_sn}:{cup_code}"
            if cup_info.get('empty') or cup_info.get('damaged'):
                redis_conn.set(cup_stock_key, 0)
            else:
                if redis_conn.get(cup_stock_key) is None:
                    redis_conn.set(cup_stock_key, 100)

        # 3. 写入完整监控快照，用于 REST API 与前端直接快速获取
        snapshot_key = f"automake:monitor:snapshot:{device_sn}"
        snapshot_json = json.dumps(parsed_data, ensure_ascii=False)
        redis_conn.set(snapshot_key, snapshot_json)

        # 4. 写入设备状态上报状态字
        state_key = f"{device_sn}_states"
        redis_conn.set(state_key, snapshot_json)

        # 5. 更新心跳时间戳
        heartbeat_key = f"automake:heartbeat:{device_sn}"
        redis_conn.set(heartbeat_key, timezone.now().timestamp())

        logger.debug(f"[Monitor] 成功更新设备 {device_sn} 的 Redis 状态与物料库存")
    except Exception as e:
        logger.error(f"[Monitor] 写入 Redis 异常: device_sn={device_sn}, error={e}")


def check_and_trigger_alerts(device: Device, parsed_data: dict) -> None:
    """
    检查异常并按需触发短信报警（带 Redis 1小时防抖）及记录 DeviceAlarm。
    """
    if not device:
        return

    abnormalities = parsed_data.get('abnormalities', {})
    if not abnormalities:
        return

    redis_conn = get_redis_connection("default")

    store_name = device.store.name if device.store else "智能咖啡机"
    contact_phone = (device.store.contact_phone if device.store and device.store.contact_phone else "138001380001")

    for alert_key, desc in abnormalities.items():
        if '.empty' in alert_key or '.low' in alert_key or 'cup.' in alert_key or 'ice.a3' in alert_key:
            alarm_type = DeviceAlarm.ALARM_LOW_MATERIAL
        elif 'disconnected' in alert_key:
            alarm_type = DeviceAlarm.ALARM_OFFLINE
        else:
            alarm_type = DeviceAlarm.ALARM_FAULT

        # 记录数据库告警表 (DeviceAlarm)
        try:
            unresolved = DeviceAlarm.objects.filter(
                device=device,
                alarm_type=alarm_type,
                detail__contains=alert_key,
                is_resolved=False
            ).first()
            if not unresolved:
                DeviceAlarm.objects.create(
                    device=device,
                    alarm_type=alarm_type,
                    detail=f"[{alert_key}] {desc}"
                )
        except Exception as e:
            logger.warning(f"[Alert] 记录 DeviceAlarm 失败: {e}")

        # 短信防抖锁：1 小时内相同设备的相同异常仅发送一次短信
        sms_debounce_key = f"automake:sms_lock:{device.device_sn}:{alert_key}"
        if redis_conn.set(sms_debounce_key, "1", ex=3600, nx=True):
            template_param = json.dumps({
                "store": store_name[:10],
                "device": device.device_sn[:15],
                "msg": desc[:20]
            }, ensure_ascii=False)
            
            logger.info(f"[Alert] 触发短信告警: device_sn={device.device_sn}, phone={contact_phone}, desc={desc}")
            try:
                send_sms_notify(
                    phone_numbers=contact_phone,
                    template_param=template_param
                )
            except Exception as se:
                logger.error(f"[Alert] 发送短信告警异常: {se}")

            # 记录系统通知事件
            try:
                NotifyEvent.objects.create(
                    level=NotifyEvent.LEVEL_WARNING if alarm_type == DeviceAlarm.ALARM_LOW_MATERIAL else NotifyEvent.LEVEL_CRITICAL,
                    event_type=NotifyEvent.EVENT_DEVICE_ALERT,
                    device=device,
                    title=f"设备告警: {desc[:20]}",
                    content=f"门店【{store_name}】设备 (SN: {device.device_sn}) 发生告警：{desc}",
                    extra_data={'alert_key': alert_key, 'parsed': parsed_data.get('display_status')}
                )
            except Exception as ne:
                logger.warning(f"[Alert] 记录 NotifyEvent 失败: {ne}")


def sync_to_mysql_if_changed(device: Device, parsed_data: dict) -> DeviceMonitorSnapshot:
    """
    仅在健康状态、部件异常或在线状态发生改变时写入 MySQL，避免高频写入开销。
    """
    device_sn = parsed_data['device_sn']
    is_healthy = parsed_data['healthy']
    is_disconnected = parsed_data['disconnected']
    abnormalities = parsed_data['abnormalities']
    free_mem = parsed_data['free']
    raw_payload = parsed_data['raw_data']

    # 1. 更新 Device 主表状态与最后心跳
    if device:
        hardware_fault_keys = [
            k for k in abnormalities 
            if not k.endswith('.empty') and not k.endswith('.low') and not k.endswith('.a2')
        ]
        if is_disconnected:
            current_status = Device.STATUS_OFFLINE
        elif hardware_fault_keys or not is_healthy:
            current_status = Device.STATUS_FAULT
        else:
            current_status = Device.STATUS_ONLINE

        old_status = device.status
        device.status = current_status
        device.last_heartbeat_at = timezone.now()
        device.save(update_fields=['status', 'last_heartbeat_at', 'updated_at'])

        if old_status != current_status:
            DeviceStatusLog.objects.create(
                device=device,
                status=current_status,
                remark=f"设备状态流转: {old_status} -> {current_status}",
                raw_payload=raw_payload
            )

    # 2. 检查 DeviceMonitorSnapshot 是否需要保存新快照
    latest_snapshot = DeviceMonitorSnapshot.objects.filter(device_sn=device_sn).order_by('-reported_at').first()
    should_save = False

    if not latest_snapshot:
        should_save = True
    elif (latest_snapshot.healthy != is_healthy or
          latest_snapshot.disconnected != is_disconnected or
          latest_snapshot.abnormality != abnormalities):
        should_save = True

    snapshot = latest_snapshot
    if should_save:
        snapshot = DeviceMonitorSnapshot.objects.create(
            device_sn=device_sn,
            healthy=is_healthy,
            disconnected=is_disconnected,
            last_time=int(timezone.now().timestamp() * 1000),
            mem_size=free_mem,
            abnormality=abnormalities,
            raw_data=raw_payload
        )
        logger.info(f"[Monitor] 设备 {device_sn} 状态变化，已生成新监控快照 (healthy={is_healthy}, status={parsed_data['display_status']})")

    return snapshot


def broadcast_monitor_status(device_sn: str, parsed_data: dict) -> None:
    """
    通过 Django Channels 异步向监控大屏 WebSocket 分组广播实时状态。
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            push_payload = {
                'type': 'device_status',
                'device_sn': device_sn,
                'display_status': parsed_data.get('display_status', 'normal'),
                'healthy': parsed_data.get('healthy', True),
                'disconnected': parsed_data.get('disconnected', False),
                'free': parsed_data.get('free', {}),
                'temperature': parsed_data.get('temperature', {}),
                'materials': parsed_data.get('materials', {}),
                'cups': parsed_data.get('cups', {}),
                'barrels': parsed_data.get('barrels', {}),
                'raw_data': parsed_data.get('raw_data', {}),
                'abnormalities': parsed_data.get('abnormalities', {}),
                'reported_at': parsed_data.get('reported_at'),
            }
            async_to_sync(channel_layer.group_send)(
                'monitor_dashboard',
                {
                    'type': 'monitor.device_status',
                    'payload': push_payload
                }
            )
    except Exception as e:
        logger.warning(f"[Monitor] WebSocket 广播异常: {e}")


def process_device_status_report(device_sn: str, raw_data: dict) -> dict:
    """
    统一入口：解析状态数据 -> 写入 Redis -> 触发短信与告警 -> 按需持久化 MySQL -> 广播 WebSocket
    
    :param device_sn: 设备序列号
    :param raw_data: 状态 JSON 数据
    :return: 结构化解析结果
    """
    # 1. 前置 JSON 解析与多料桶聚合
    parsed_data = parse_device_status_payload(device_sn, raw_data)

    # 2. 写入 Redis（纯数值库存与结构化快照）
    update_device_status_to_redis(device_sn, parsed_data)

    # 3. 关联设备模型并执行告警检查与 MySQL 条件更新
    device = Device.objects.filter(device_sn=device_sn).select_related('store').first()
    if device:
        check_and_trigger_alerts(device, parsed_data)
        sync_to_mysql_if_changed(device, parsed_data)

    # 4. WebSocket 监控大屏推送广播
    broadcast_monitor_status(device_sn, parsed_data)

    return parsed_data


def persist_device_barrels_to_mysql(device_sn: str) -> bool:
    """
    将当前设备在 Redis 中的最新料桶状态及聚合余量持久化存入 MySQL 数据库。
    (用于超过 70s 未收到上位机上报时的超时固化降级)
    """
    try:
        from devices.models import Device, DeviceMaterialStock
        from inventory.models import Material

        device = Device.objects.filter(device_sn=device_sn).select_related('store').first()
        if not device:
            return False

        redis_conn = get_redis_connection("default")
        
        # 1. 从 Redis 快照或实时库存读取
        snapshot_json = redis_conn.get(f"automake:monitor:snapshot:{device_sn}")
        materials_data = {}
        if snapshot_json:
            if isinstance(snapshot_json, bytes):
                snapshot_json = snapshot_json.decode('utf-8')
            snap = json.loads(snapshot_json)
            materials_data = snap.get('materials', {})

        if not materials_data:
            keys = redis_conn.keys(f"automake:stock:{device_sn}:*")
            for k in keys:
                k_str = k.decode('utf-8') if isinstance(k, bytes) else str(k)
                mat_code = k_str.split(':')[-1]
                val = redis_conn.get(k)
                if val is not None:
                    try:
                        materials_data[mat_code] = {'total_volume': float(val)}
                    except (ValueError, TypeError):
                        pass

        # 2. 持久化更新 DeviceMaterialStock
        for mat_code, info in materials_data.items():
            vol = float(info.get('total_volume', 0)) if isinstance(info, dict) else float(info)
            mat_obj = Material.objects.filter(code=mat_code).first()
            if mat_obj and getattr(mat_obj, 'material_type', 'ingredient') in ('ingredient', 'solid', 'thin', 'thick'):
                stock_obj = DeviceMaterialStock.objects.filter(device=device, code=mat_code).first()
                if not stock_obj:
                    stock_obj = DeviceMaterialStock.objects.create(
                        device=device,
                        code=mat_code,
                        name=mat_obj,
                        current_remaining_height=Decimal(str(vol)),
                        warn_level=Decimal('100.00')
                    )
                else:
                    stock_obj.current_remaining_height = Decimal(str(vol))
                    stock_obj.save(update_fields=['current_remaining_height', 'updated_at'])

        logger.info(f"[Monitor] 超过 70s 未收到上位机上报，已成功将设备 {device_sn} 的料桶信息持久化写入 MySQL")
        return True
    except Exception as e:
        logger.error(f"[Monitor] 持久化料桶信息到 MySQL 异常, device_sn={device_sn}: {e}")
        return False


def check_and_persist_barrels_on_timeout(device_sn: str, timeout_seconds: int = 70) -> bool:
    """
    检查指定设备是否超过 70s 未收到上位机上报，若超时则触发持久化到 MySQL。
    """
    try:
        redis_conn = get_redis_connection("default")
        heartbeat_ts = redis_conn.get(f"automake:heartbeat:{device_sn}")
        if heartbeat_ts:
            last_ts = float(heartbeat_ts)
            now_ts = timezone.now().timestamp()
            if (now_ts - last_ts) > timeout_seconds:
                return persist_device_barrels_to_mysql(device_sn)
        return False
    except Exception as e:
        logger.warning(f"[Monitor] 检查设备 {device_sn} 心跳超时异常: {e}")
        return False
