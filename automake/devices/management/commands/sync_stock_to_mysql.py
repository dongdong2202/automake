import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django_redis import get_redis_connection
from devices.models import Device, DeviceConsumableStock, DeviceMaterialStock
from inventory.models import Material

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "定时将 Redis 中的物料与耗材物理库存 (automake:stock:{device_sn}:*) 批量同步回写至 MySQL (每30分钟执行)"

    def add_arguments(self, parser):
        parser.add_argument('--sn', type=str, default=None, help='指定同步的设备编号（默认全量同步）')

    def handle(self, *args, **options):
        target_sn = options.get('sn')
        redis_conn = get_redis_connection("default")

        devices_qs = Device.objects.all()
        if target_sn:
            devices_qs = devices_qs.filter(device_sn=target_sn)

        total_synced_consumables = 0
        total_synced_materials = 0

        consumable_codes = set(
            Material.objects.filter(
                material_type__in=[Material.TYPE_CONSUMABLE, Material.TYPE_CUP]
            ).values_list('code', flat=True)
        )
        consumable_codes.update(['paperL', 'paperM', 'plasticL', 'plasticM', 'lid', 'membrane'])

        for device in devices_qs:
            prefix = f"automake:stock:{device.device_sn}:"
            keys = redis_conn.keys(f"{prefix}*")
            if not keys:
                continue

            for raw_k in keys:
                k_str = raw_k.decode('utf-8') if isinstance(raw_k, bytes) else raw_k
                mat_code = k_str.replace(prefix, '')
                raw_val = redis_conn.get(raw_k)
                if raw_val is None:
                    continue

                try:
                    val_float = float(raw_val)
                except (ValueError, TypeError):
                    continue

                if mat_code in consumable_codes:
                    # 耗材/杯型 -> DeviceConsumableStock (1:1 真实物理数量)
                    final_qty = int(val_float)
                    mat_obj = Material.objects.filter(code=mat_code).first()
                    if mat_obj:
                        cs, created = DeviceConsumableStock.objects.get_or_create(
                            device=device, code=mat_obj,
                            defaults={'quantity': final_qty, 'init_quantity': 100}
                        )
                        if not created and cs.quantity != final_qty:
                            DeviceConsumableStock.objects.filter(pk=cs.pk).update(quantity=final_qty)
                        total_synced_consumables += 1
                else:
                    # 原材料/食材 -> DeviceMaterialStock
                    mat_obj = Material.objects.filter(code=mat_code).first()
                    if mat_obj:
                        ms = DeviceMaterialStock.objects.filter(device=device, code=mat_code).first()
                        if ms:
                            DeviceMaterialStock.objects.filter(pk=ms.pk).update(current_remaining_height=Decimal(str(val_float)))
                            total_synced_materials += 1

        self.stdout.write(self.style.SUCCESS(
            f"库存同步成功！已更新 {total_synced_consumables} 条耗材库存记录，{total_synced_materials} 条食材库存记录。"
        ))
