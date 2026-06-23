"""
monitor/models.py —— 设备监控快照模型

每台设备连接上报 status_report 时，将最新状态保存/更新到此表。
字段按照上位机协议字段原样存储（JSONField），便于灵活扩展。
"""

from django.db import models


class DeviceMonitorSnapshot(models.Model):
    """
    设备监控快照表

    每台设备对应一条记录（以 device_sn 为唯一键），
    每次收到 status_report 消息时原地更新（upsert），
    始终保存该设备的最新状态。

    字段说明：
      - device_sn:      设备序列号（唯一标识，对应 Device.device_sn）
      - healthy:        整机健康状态（false = 有异常）
      - disconnected:   是否断线
      - last_time:      上位机上报的时间戳（毫秒）
      - mem_size:       内存信息，如 {"master": 1024, "slave": 1024}
      - abnormality:    各传感器/执行机构异常状态（JSON）
      - raw_data:       原始上报 data 字段完整存储（便于排查）
      - reported_at:    最后上报时间（服务端时间）
    """

    device_sn = models.CharField(
        max_length=128, unique=True, db_index=True,
        verbose_name='设备序列号'
    )
    # 整机健康：false 表示存在异常，应显示红色警告或闪烁
    healthy = models.BooleanField(default=True, verbose_name='整机健康')
    # 是否断线（上位机自报）
    disconnected = models.BooleanField(default=False, verbose_name='是否断线')
    # 上位机上报的时间戳（毫秒）
    last_time = models.BigIntegerField(default=0, verbose_name='上报时间戳(ms)')
    # 内存/容量信息（JSON），如 {"master": 1024, "slave": 1024}
    mem_size = models.JSONField(default=dict, blank=True, verbose_name='内存信息')
    # 传感器/执行机构异常信息（JSON），结构与协议 abnormality 字段一致
    abnormality = models.JSONField(default=dict, blank=True, verbose_name='异常详情')
    # 原始 data 字段，完整保存便于调试
    raw_data = models.JSONField(default=dict, blank=True, verbose_name='原始上报数据')
    # 服务端最后收到该设备状态上报的时间
    reported_at = models.DateTimeField(auto_now=True, verbose_name='最后上报时间')
    # 服务端首次收到该设备状态上报的时间
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次上报时间')

    class Meta:
        db_table = 'device_monitor_snapshot'
        verbose_name = '设备监控快照'
        verbose_name_plural = '设备监控快照列表'
        ordering = ['device_sn']

    def __str__(self):
        status = '健康' if self.healthy else '异常'
        return f'{self.device_sn} [{status}]'

    @property
    def display_status(self):
        """
        返回前端展示状态字符串：
          - 'normal':   绿色正常（healthy=True，disconnected=False）
          - 'warning':  红色警告（healthy=False，disconnected=False）
          - 'fault':    红色闪烁故障（disconnected=True 或 healthy=False 且有严重异常）
        """
        if self.disconnected:
            return 'fault'
        if not self.healthy:
            return 'warning'
        return 'normal'
