"""/api/ 楼栋过滤（阶段一第二批，隐患 #3：API 层无楼栋过滤）。

admin 侧早有 BuildingScopeMixin，但 /api/ 全量返回——楼栋负责人经
Agent 查询能看全院数据，权限形同虚设。本模块把楼栋可见范围引入 API：

scope 来源（resolve_building_scope）：
- key 路径（X-API-Key，dl-control 机器调用）：读 X-Building 头。
  楼栋名是中文，HTTP 头只可靠传输 ASCII——dl-control 侧 percent-encode
  （quote），本侧 unquote 还原；不含 % 的值 unquote 为原样，故裸中文
  （进程内测试直传）也兼容。
  空/缺省 → None（全院，向后兼容——dl-control 升级发头前一切照旧）；
  非空但床位台账 Building 表查无此名 → 400（fail-loud：dl-control 侧
  楼栋名与台账失配时立即暴露，而非静默放过全量数据）
- session 路径（浏览器已登录用户）：员工档案 Employee.building；
  superuser / 无员工档案 / 楼栋为空 → None（全院，fail-open 同 admin 侧）。
  一律忽略 X-Building 头——session 用户的范围只来自档案，防伪造。

语义约定：
- scope_filter：列表用。scope 与显式 ?building= 参数 AND 叠加
  （冲突自然得空集，无需特判）
- scope_get_or_404：详情读用。越权与不存在统一 404，不泄露存在性
- resident_for_write：写路径用。不存在 → 404；越权 → 403（明示权限
  边界，写操作要让调用方知道"看得见但改不得"）
- beds 的统计类端点例外：scope 直接覆盖 ?building= 参数——楼长问
  入住率时答案就是本楼，叠加只会得到冲突空集（beds/api.py 内联处理）
"""

from urllib.parse import unquote

from django.apps import apps
from ninja.errors import HttpError


def resolve_building_scope(request) -> str | None:
    """解析本次请求的楼栋范围：None = 全院。"""
    if request.auth == "api-key":
        raw = (request.headers.get("X-Building", "") or "").strip()
        name = unquote(raw).strip()
        if not name:
            return None
        building_model = apps.get_model("beds", "Building")
        if not building_model.objects.filter(name=name).exists():
            raise HttpError(400, f"X-Building 楼栋未知名：{name}（须与床位台账楼栋名一致）")
        return name

    # session 路径：范围只来自员工档案；忽略 X-Building 头（防伪造）
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.is_superuser:
        return None
    try:
        employee = user.employee
    except Exception:
        return None  # 无员工档案 → 全院（与 admin 侧 fail-open 一致）
    building = (employee.building or "").strip()
    return building or None


def scope_filter(qs, request, field: str = "building"):
    """列表过滤：scope 与调用方已有的 ?building= 等参数 AND 叠加。"""
    scope = resolve_building_scope(request)
    return qs.filter(**{field: scope}) if scope else qs


def scope_get_or_404(model, pk, request, field: str = "building"):
    """详情读：越权与不存在统一 404（顺带修复缺失 id 裸 get 的 500）。"""
    scope = resolve_building_scope(request)
    qs = model.objects.all()
    if scope:
        qs = qs.filter(**{field: scope})
    obj = qs.filter(pk=pk).first()
    if obj is None:
        raise HttpError(404, f"{model._meta.verbose_name}不存在或无权访问")
    return obj


def resident_for_write(request, resident_id: int):
    """写路径取老人：不存在 → 404；不在本楼 → 403。"""
    from residents.models import Resident

    resident = Resident.objects.filter(pk=resident_id).first()
    if resident is None:
        raise HttpError(404, "老人不存在")
    scope = resolve_building_scope(request)
    if scope and resident.building != scope:
        raise HttpError(403, f"无权操作 {resident.building} 的老人（当前范围：{scope}）")
    return resident
