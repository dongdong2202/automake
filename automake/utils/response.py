"""
统一响应格式工具

所有 API 响应统一包装为：
{
    "code": 0,          # 0 表示成功，非 0 表示错误
    "message": "ok",
    "data": { ... }
}
"""

from rest_framework.response import Response


def ok(data=None, message='ok') -> Response:
    """
    成功响应
    :param data: 返回数据
    :param message: 描述信息
    """
    return Response({
        'code': 0,
        'message': message,
        'data': data,
    })


def error(message='请求失败', code=1, status=400) -> Response:
    """
    错误响应
    :param message: 错误描述
    :param code: 业务错误码（非 0）
    :param status: HTTP 状态码
    """
    return Response({
        'code': code,
        'message': message,
        'data': None,
    }, status=status)
