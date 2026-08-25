"""/api/* 写请求自动留痕（兜底层，2026-08-25）。

规则：
- 只记变更方法（POST/PUT/PATCH/DELETE），GET 无痕；
- 显式埋点（record()）已记的请求跳过——一事一行；
- /admin/* 由 Django LogEntry 覆盖，/api/family/auth/ 带密码，均不记；
- 不落请求体——敏感字段零接触，兜底行只有 谁打了哪个接口/状态码。
"""

import contextlib

from .models import OperationLog
from .record import client_ip, resolve_actor

_PATH_LABELS = [
    ("/api/meal-order-ocr", "点餐OCR识别"),
    ("/api/menu-ocr", "菜单OCR识别"),
    ("/api/meal-orders", "点餐接口"),
    ("/api/meal-finance", "餐费月结"),
    ("/api/health-records", "健康记录录入"),
    ("/api/nursing-logs", "护理日志接口"),
    ("/api/assessments", "评估接口"),
    ("/api/billing", "账单接口"),
    ("/api/incidents", "异常上报接口"),
    ("/api/family", "家属端接口"),
]
_SKIP_PREFIXES = ("/api/family/auth/",)
_MUTATING = ("POST", "PUT", "PATCH", "DELETE")


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        with contextlib.suppress(Exception):  # 留痕失败不影响业务响应
            self._maybe_log(request, response)
        return response

    def _maybe_log(self, request, response):
        if request.method not in _MUTATING:
            return
        path = request.path
        if not path.startswith("/api/") or path.startswith(_SKIP_PREFIXES):
            return
        if getattr(request, "_audit_logged", False):
            return
        label = next((v for k, v in _PATH_LABELS if path.startswith(k)), None)
        atype, aname, user = resolve_actor(request)
        OperationLog.objects.create(
            actor_type=atype, actor_name=aname, user=user,
            action=label or "接口写操作",
            method=request.method, path=path[:200],
            status_code=response.status_code, ip=client_ip(request),
        )
