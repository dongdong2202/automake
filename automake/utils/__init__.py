"""
AutoMake 通用工具包 (utils)

提供跨模块复用的通用基础组件：
- response: 统一 REST API 响应格式 (ok, error)
- permissions: 自定义 DRF 角色权限类 (IsSuperAdmin, IsAdmin, IsMaterialAdmin, IsCustomer)
- wechat: 微信小程序及微信支付 V3 API 调用封装
- redis_keys: Redis 统一键名规范
"""

from .response import ok, error
from .permissions import IsSuperAdmin, IsAdmin, IsMaterialAdmin, IsCustomer
from .redis_keys import get_stock_key, get_monitor_snapshot_key, get_device_ws_group

__all__ = [
    'ok',
    'error',
    'IsSuperAdmin',
    'IsAdmin',
    'IsMaterialAdmin',
    'IsCustomer',
    'get_stock_key',
    'get_monitor_snapshot_key',
    'get_device_ws_group',
]
