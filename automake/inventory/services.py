"""
进销存批次跟踪与 FEFO（First Expired, First Out，先到期先出库）核心服务模块
"""

import logging
from decimal import Decimal
from typing import List, Optional, Tuple, Union

from django.db import models, transaction
from django.core.exceptions import ValidationError

from inventory.models import (
    Material,
    InventoryRecord,
    StoreInventory,
    StoreInventoryBatch,
    StoreInventoryRecord,
    generate_batch_no,
)
from stores.models import Store
from devices.models import Device, DeviceConsumableStock

logger = logging.getLogger(__name__)


def create_inbound_batch(
    material: Union[int, Material],
    quantity: Union[Decimal, float, int, str],
    price: Optional[Union[Decimal, float, int, str]] = None,
    expiration_date=None,
    batch_no: Optional[str] = None,
    operator=None,
    remarks: str = '',
    explicit_no_expiration: bool = False,
) -> InventoryRecord:
    """
    登记总仓物料入库批次
    1. 校验/生成全局唯一批次号 batch_no
    2. 初始化批次剩余数量 remaining_quantity = quantity
    3. 记录采购进价与过期时间
    4. 原子增加 Material.quantity
    """
    if isinstance(material, (int, str)):
        material_obj = Material.objects.filter(pk=int(material)).first()
        if not material_obj:
            raise ValidationError(f"物料 ID {material} 不存在")
    else:
        material_obj = material

    qty_decimal = Decimal(str(quantity))
    if qty_decimal <= 0:
        raise ValidationError("入库数量必须大于 0")

    price_decimal = Decimal(str(price)) if price is not None else None
    if price_decimal is not None and price_decimal < 0:
        raise ValidationError("采购单价不能为负数")

    final_batch_no = (batch_no or '').strip() or generate_batch_no()

    # 校验批次号在当前物料中是否重复入库
    if InventoryRecord.objects.filter(
        material=material_obj,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        batch_no=final_batch_no,
    ).exists():
        raise ValidationError(f"物料 [{material_obj.name}] 批次号 [{final_batch_no}] 已存在，请勿重复入库")

    record = InventoryRecord(
        material=material_obj,
        record_type=InventoryRecord.RECORD_TYPE_IN,
        quantity=qty_decimal,
        price=price_decimal,
        expiration_date=expiration_date,
        batch_no=final_batch_no,
        remaining_quantity=qty_decimal,
        operator=operator,
        remarks=remarks,
    )
    if explicit_no_expiration:
        record._explicit_no_expiration = True

    record.save()
    logger.info(
        f"[InventoryService] 入库批次创建成功: material={material_obj.name}, batch_no={final_batch_no}, "
        f"qty={qty_decimal}, price={price_decimal}, exp={record.expiration_date}"
    )
    return record


def dispatch_outbound_fefo(
    material: Union[int, Material],
    total_quantity: Union[Decimal, float, int, str],
    store: Union[int, Store],
    operator=None,
    remarks: str = '',
) -> List[InventoryRecord]:
    """
    总仓分拨出库 FEFO 自动分配核销算法
    1. 事务加锁物料与有效入库批次；
    2. 校验总仓总库存与可用批次总量是否充足；
    3. 按照 FEFO 规则（到期日升序 NULLS LAST，入库时间升序）逐一扣减批次；
    4. 对扣减的各个批次分别生成 InventoryRecord 出库记录（严格继承原批次进价与批次号）；
    5. InventoryRecord.save 内部自动维护门店聚合库存 StoreInventory、门店批次 StoreInventoryBatch 及调拨流水 StoreInventoryRecord；
    6. 返回拆批生成的出库记录列表。
    """
    qty_needed = Decimal(str(total_quantity))
    if qty_needed <= 0:
        raise ValidationError("出库数量必须大于 0")

    material_id = material.pk if isinstance(material, Material) else int(material)
    store_id = store.pk if isinstance(store, Store) else int(store)

    with transaction.atomic():
        # 1. 锁查物料主记录
        mat_obj = Material.objects.select_for_update().filter(pk=material_id).first()
        if not mat_obj:
            raise ValidationError(f"物料 ID {material_id} 不存在")

        store_obj = Store.objects.filter(pk=store_id).first()
        if not store_obj:
            raise ValidationError(f"门店 ID {store_id} 不存在")

        if mat_obj.quantity < qty_needed:
            raise ValidationError(
                f"物料 [{mat_obj.name}] 总仓库存不足，当前库存 {mat_obj.quantity}，申请出库 {qty_needed}"
            )

        # 2. 锁查该物料所有具有剩余量的有效入库批次，排序规则：先到期先出库（None 排在最后），同到期日按入库先后
        inbound_batches = list(
            InventoryRecord.objects.select_for_update()
            .filter(
                material=mat_obj,
                record_type=InventoryRecord.RECORD_TYPE_IN,
                remaining_quantity__gt=Decimal('0.00'),
            )
            .order_by(models.F('expiration_date').asc(nulls_last=True), 'created_at')
        )

        total_batch_available = sum((b.remaining_quantity for b in inbound_batches), Decimal('0.00'))
        if total_batch_available < qty_needed:
            raise ValidationError(
                f"物料 [{mat_obj.name}] 可用入库批次总余量不足（批次可用量: {total_batch_available}，申请出库: {qty_needed}）"
            )

        # 3. 循环扣减（FEFO Allocation）
        remaining_need = qty_needed
        outbound_records = []

        for batch in inbound_batches:
            if remaining_need <= Decimal('0.00'):
                break

            deduct_qty = min(batch.remaining_quantity, remaining_need)
            batch.remaining_quantity -= deduct_qty
            batch.save(update_fields=['remaining_quantity'])

            # 创建出库记录
            sub_remarks = f"{remarks} [核销批次 {batch.batch_no}]" if remarks else f"FEFO 分拨出库 (核销批次 {batch.batch_no})"
            out_record = InventoryRecord(
                material=mat_obj,
                record_type=InventoryRecord.RECORD_TYPE_OUT,
                quantity=deduct_qty,
                price=batch.price,
                store=store_obj,
                operator=operator,
                expiration_date=batch.expiration_date,
                batch_no=batch.batch_no,
                source_batch=batch,
                remarks=sub_remarks,
            )
            out_record.save()
            outbound_records.append(out_record)

            remaining_need -= deduct_qty

        logger.info(
            f"[InventoryService] FEFO 分拨完成: material={mat_obj.name}, store={store_obj.name}, "
            f"total_qty={qty_needed}, 拆分批次数={len(outbound_records)}"
        )
        return outbound_records


def dispatch_store_to_device_fefo(
    store: Union[int, Store],
    material: Union[int, Material],
    device: Union[int, Device],
    quantity: Union[Decimal, float, int, str],
    operator=None,
    remarks: str = '',
) -> Tuple[StoreInventory, List[StoreInventoryRecord]]:
    """
    门店出库加料到设备 FEFO 流转核心算法
    1. 锁查门店聚合总库存 StoreInventory；
    2. 按照 FEFO 规则（到期日升序 NULLS LAST，入店时间升序）锁查该门店 StoreInventoryBatch；
    3. 扣减批次库存，并为各个扣减分录创建携带 batch_no、cost_price、expiration_date 的 StoreInventoryRecord；
    4. 扣减门店聚合总库存 StoreInventory；
    5. 若物料为耗材/杯，同步维护 DeviceConsumableStock；
    6. 返回 (store_inv, created_records)。
    """
    qty_needed = Decimal(str(quantity))
    if qty_needed <= 0:
        raise ValidationError("出库加料数量必须大于 0")

    store_id = store.pk if isinstance(store, Store) else int(store)
    material_id = material.pk if isinstance(material, Material) else int(material)
    device_id = device.pk if isinstance(device, Device) else int(device)

    with transaction.atomic():
        store_obj = Store.objects.filter(pk=store_id).first()
        if not store_obj:
            raise ValidationError(f"门店 ID {store_id} 不存在")

        mat_obj = Material.objects.filter(pk=material_id).first()
        if not mat_obj:
            raise ValidationError(f"物料 ID {material_id} 不存在")

        dev_obj = Device.objects.filter(pk=device_id).first()
        if not dev_obj:
            raise ValidationError(f"设备 ID {device_id} 不存在")

        store_inv = StoreInventory.objects.select_for_update().filter(store=store_obj, material=mat_obj).first()
        if not store_inv or store_inv.quantity < qty_needed:
            cur_qty = store_inv.quantity if store_inv else Decimal('0.00')
            raise ValidationError(f"门店 [{store_obj.name}] 物料 [{mat_obj.name}] 库存不足（在店库存: {cur_qty}，申请加料: {qty_needed}）")

        # 锁查门店批次
        store_batches = list(
            StoreInventoryBatch.objects.select_for_update()
            .filter(
                store=store_obj,
                material=mat_obj,
                quantity__gt=Decimal('0.00'),
            )
            .order_by(models.F('expiration_date').asc(nulls_last=True), 'created_at')
        )

        batch_available = sum((b.quantity for b in store_batches), Decimal('0.00'))
        created_records = []
        remaining_need = qty_needed

        if batch_available >= qty_needed:
            # 门店批次充足，严格按 FEFO 扣减各个批次
            for s_batch in store_batches:
                if remaining_need <= Decimal('0.00'):
                    break
                deduct_qty = min(s_batch.quantity, remaining_need)
                s_batch.quantity -= deduct_qty
                s_batch.save(update_fields=['quantity', 'updated_at'])

                rec = StoreInventoryRecord.objects.create(
                    store=store_obj,
                    material=mat_obj,
                    device=dev_obj,
                    record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
                    quantity=deduct_qty,
                    operator=operator,
                    batch_no=s_batch.batch_no,
                    cost_price=s_batch.cost_price,
                    expiration_date=s_batch.expiration_date,
                    remarks=remarks or f'门店出库加料到设备 [{dev_obj.device_name or dev_obj.device_sn}] (批次: {s_batch.batch_no})'
                )
                created_records.append(rec)
                remaining_need -= deduct_qty
        else:
            # 兼容历史存量无批次数据：若批次不够但聚合库存够，先扣完批次，剩余部分生成无批次流水
            for s_batch in store_batches:
                if remaining_need <= Decimal('0.00'):
                    break
                deduct_qty = min(s_batch.quantity, remaining_need)
                s_batch.quantity -= deduct_qty
                s_batch.save(update_fields=['quantity', 'updated_at'])

                rec = StoreInventoryRecord.objects.create(
                    store=store_obj,
                    material=mat_obj,
                    device=dev_obj,
                    record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
                    quantity=deduct_qty,
                    operator=operator,
                    batch_no=s_batch.batch_no,
                    cost_price=s_batch.cost_price,
                    expiration_date=s_batch.expiration_date,
                    remarks=remarks or f'门店出库加料到设备 [{dev_obj.device_name or dev_obj.device_sn}] (批次: {s_batch.batch_no})'
                )
                created_records.append(rec)
                remaining_need -= deduct_qty

            if remaining_need > Decimal('0.00'):
                rec = StoreInventoryRecord.objects.create(
                    store=store_obj,
                    material=mat_obj,
                    device=dev_obj,
                    record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
                    quantity=remaining_need,
                    operator=operator,
                    batch_no='',
                    cost_price=mat_obj.price,
                    expiration_date=None,
                    remarks=remarks or f'门店出库加料到设备 [{dev_obj.device_name or dev_obj.device_sn}] (历史无批次库存)'
                )
                created_records.append(rec)

        # 扣减门店总库存
        store_inv.quantity -= qty_needed
        store_inv.save(update_fields=['quantity', 'updated_at'])

        # 如果是耗材（如纸杯/杯盖/塑料杯/封口膜），更新设备耗材库存追踪表
        if mat_obj.material_type in ['consumable', 'cup']:
            dev_consumable, _ = DeviceConsumableStock.objects.get_or_create(
                device=dev_obj,
                code_id=mat_obj.code,
                defaults={'quantity': 0, 'unit': mat_obj.unit or '个'}
            )
            dev_consumable.quantity += int(qty_needed)
            dev_consumable.save()

        logger.info(
            f"[InventoryService] 门店出库加料完成: store={store_obj.name}, device={dev_obj.device_sn}, "
            f"material={mat_obj.name}, quantity={qty_needed}, 分批记录数={len(created_records)}"
        )
        return store_inv, created_records


def update_device_consumable_stock(
    device: Device,
    items: List[dict],
    operator=None,
    remarks: str = 'Web管理端录入'
) -> List[dict]:
    """
    统一设备耗材录入与双写服务：
    1. 事务锁定并更新 MySQL DeviceConsumableStock
    2. 生成 StoreInventoryRecord 门店出库加料/盘点流水记录
    3. 立即原子同步写入 Redis automake:stock:{sn}:{code} (真实物理件数，严禁放大100倍)
    4. 若库存高于预警阈值，清除短信预警防抖锁
    """
    from django_redis import get_redis_connection
    try:
        redis_conn = get_redis_connection("default")
    except Exception:
        redis_conn = None

    updated = []
    with transaction.atomic():
        for item in items:
            code = item.get('code')
            if not code:
                continue
            quantity = int(item.get('quantity', 0))

            material, _ = Material.objects.get_or_create(
                code=code,
                defaults={
                    'name': code,
                    'material_type': Material.TYPE_CUP if code in {'paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'} else Material.TYPE_CONSUMABLE,
                    'unit': '张' if code == 'membrane' else '个'
                }
            )

            stock, created = DeviceConsumableStock.objects.select_for_update().get_or_create(
                device=device,
                code=material,
                defaults={
                    'quantity': quantity,
                    'init_quantity': max(100, quantity),
                    'unit': material.unit or '个'
                }
            )
            old_qty = stock.quantity
            stock.quantity = quantity
            stock.save(update_fields=['quantity', 'updated_at'])

            # 记录流水台账
            if device.store:
                StoreInventoryRecord.objects.create(
                    store=device.store,
                    material=material,
                    device=device,
                    record_type=StoreInventoryRecord.TYPE_OUT_TO_DEVICE,
                    quantity=Decimal(str(quantity)),
                    operator=operator,
                    cost_price=material.price,
                    remarks=f"{remarks}: 原存量={old_qty}, 调整为={quantity}"
                )

            # 同步更新 Redis (真实物理数量，严禁放大100倍)
            if redis_conn:
                redis_key = f"automake:stock:{device.device_sn}:{code}"
                redis_conn.set(redis_key, quantity)

                # 若库存充裕，清理报警锁
                warn_threshold = int(getattr(stock, 'warn_level', 20))
                if quantity >= warn_threshold:
                    sms_lock_key = f"automake:sms_sent:{device.device_sn}:{code}"
                    redis_conn.delete(sms_lock_key)

            updated.append({'code': code, 'quantity': quantity, 'old_quantity': old_qty})

    logger.info(f"[ConsumableStock] 设备 {device.device_sn} 耗材更新完成: 操作人={operator}, 详情={updated}")
    return updated

