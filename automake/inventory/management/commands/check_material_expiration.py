"""
Django 管理命令：执行物料保质期预警检查
运行方式: python manage.py check_material_expiration [--days 30] [--force]
"""

from django.core.management.base import BaseCommand
from inventory.tasks import check_inventory_expiration_task


class Command(BaseCommand):
    help = '扫描全库物料批次保质期，对 <=30 天临期及已过期物料生成平台告警并分发短信'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='预警提前天数（默认 30 天）',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='强制触发（忽略每日防刷去重）',
        )

    def handle(self, *args, **options):
        days = options['days']
        force = options['force']

        self.stdout.write(self.style.NOTICE(f'🚀 开始执行物料保质期预警扫描 (阈值={days}天, force={force})...'))
        result = check_inventory_expiration_task(alert_days=days, force=force)

        self.stdout.write(self.style.SUCCESS(
            f'✅ 扫描完成！'
            f'扫描批次数: {result["total_scanned_batches"]}, '
            f'临期批次: {result["expiring_soon_batches"]}, '
            f'已过期批次: {result["expired_batches"]}, '
            f'本次触发告警: {result["alerted_batches"]}, '
            f'防刷跳过: {result["skipped_dedup_batches"]}'
        ))
