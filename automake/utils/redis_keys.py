"""
Redis 键名统一管理工具模块

本模块集中管理项目中所有的 Redis 键名规范，避免在业务代码中硬编码字符串，
防止因键名格式不一致或拼写错误导致的数据不同步或缓存穿透。
"""


def get_stock_key(device_sn: str, material_code: str) -> str:
    """
    生成设备物料实时库存的 Redis Key

    键名规范：automake:stock:{device_sn}:{material_code}

    Args:
        device_sn: 设备唯一序列号（如 'sn005'）
        material_code: 物料编码（如 'coffee_bean', 'paperL', 'fresh_milk'）

    Returns:
        str: 规范化的 Redis 键名字符串
    """
    return f"automake:stock:{device_sn}:{material_code}"


def get_monitor_snapshot_key(device_sn: str) -> str:
    """
    生成设备监控最新状态快照的 Redis Key

    键名规范：automake:monitor:snapshot:{device_sn}

    Args:
        device_sn: 设备唯一序列号

    Returns:
        str: 规范化的 Redis 键名字符串
    """
    return f"automake:monitor:snapshot:{device_sn}"


def get_device_ws_group(device_sn: str) -> str:
    """
    生成设备关联的 WebSocket 广播 Group 名称

    组名规范：device_{device_sn}

    Args:
        device_sn: 设备唯一序列号

    Returns:
        str: Channels Group 名称
    """
    return f"device_{device_sn}"
