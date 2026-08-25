"""显式埋点入口：关键业务动作的人话留痕。

用法（业务端点落库成功后调用，永不抛错）：

    from auditlog.record import record
    record(request, action="退餐", target=f"{r.name} 8-26 午餐",
           detail=f"原因：{reason}", target_model="meals.MealOrder",
           target_id=order.id)
"""

from .models import OperationLog


def resolve_actor(request, override_name: str = "", override_type: str | None = None):
    """从 request 解析 (actor_type, actor_name, user)。

    顺序：ninja 挂在 request.auth 上的凭据优先（FamilyMember 实例 =
    家属、"api-key" = 机器调用），其次登录 session。
    override_name 给「机器渠道转人工署名」用（如 AI 告警页转发 ERP 的
    operator=会话姓名）：署名能在员工台账查到 → 记员工；查不到 → 记
    AI 渠道带署名（诚实口径：不冒认身份）。
    """
    from family.models import FamilyMember, is_family_user

    user = getattr(request, "user", None)
    auth = getattr(request, "auth", None)

    if override_name:
        if override_type:
            return override_type, override_name[:40], None
        from staff.models import Employee

        if Employee.objects.filter(name=override_name).exists():
            return OperationLog.Actor.STAFF, override_name[:40], None
        return OperationLog.Actor.AI, override_name[:40], None

    if isinstance(auth, FamilyMember):
        return OperationLog.Actor.FAMILY, auth.name[:40], None
    if auth == "api-key":
        return OperationLog.Actor.AI, "AI 助手", None
    if user is not None and user.is_authenticated:
        if is_family_user(user):
            fm = getattr(user, "family_profile", None)
            return OperationLog.Actor.FAMILY, (fm.name if fm else user.username)[:40], user
        name = user.username
        emp = getattr(user, "employee", None)
        if emp is not None:
            name = emp.name
        return OperationLog.Actor.STAFF, name[:40], user
    return OperationLog.Actor.SYSTEM, "系统", None


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def record(request, *, action, target="", target_model="", target_id="",
           detail="", status_code=200, actor_name="", actor_type=None):
    """记一条业务操作日志。留痕永不打断业务流（内部吞错）。"""
    try:
        atype, aname, user = resolve_actor(request, actor_name, actor_type)
        OperationLog.objects.create(
            actor_type=atype, actor_name=aname, user=user,
            action=action[:30], target=target[:120],
            target_model=target_model[:50], target_id=str(target_id or "")[:20],
            detail=detail[:500],
            method=getattr(request, "method", "")[:8],
            path=getattr(request, "path", "")[:200],
            status_code=status_code, ip=client_ip(request),
        )
        # 同请求兜底层跳过：一事一行（middleware 读此标记）
        request._audit_logged = True
    except Exception:
        pass
