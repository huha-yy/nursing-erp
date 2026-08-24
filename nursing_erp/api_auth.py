"""
/api/ 接口认证（2026-08-21 P0 安全加固）。

背景：/api/ 原先无认证，且系统经 admin.eldcare.cn:8443 暴露公网后，
老人 PII（姓名/身份证/健康数据）可被匿名读取、数据可被匿名伪造。

认证方式（任一通过即可）：
1. 机器调用（ai-nursing-home 的 dl-control / Agent 技能）：
   请求头 X-API-Key 与 settings.ERP_API_KEY（.env 中配置，gitignored）一致
2. 浏览器调用（轻量页 kitchen/quick-log/menu-ocr 等页面的 JS）：
   已登录的 Django session —— fetch 同源请求自动携带 cookie

都未通过 → 401。注意：ERP_API_KEY 未配置时密钥路径永不放行（fail-closed），
不会退化为无认证。
"""

import secrets

from django.conf import settings


def erp_auth(request):
    """django-ninja 认证函数：X-API-Key 或登录 session，任一通过。"""
    # 1) 服务间调用：API key（常量时间比较，防时序侧信道）
    expected = getattr(settings, "ERP_API_KEY", "")
    provided = request.headers.get("X-API-Key", "")
    if expected and provided and secrets.compare_digest(provided, expected):
        return "api-key"

    # 2) 浏览器调用：已登录 session（AuthenticationMiddleware 已挂 request.user）
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        # 家属身份不得走员工 /api/（2026-08-24 家属端安全闭合）：
        # 家属本来无 Employee 档案，session 口径会 fail-open 到全院数据，
        # 必须在此按 FamilyMember 档案显式拒绝——家属 API 在独立的
        # /api/family/ NinjaAPI 实例上，不经过本函数。
        # 只按档案拒、不按 is_staff 拒：无档案的裸账号沿用 admin 建档
        # 语义（tests/test_api_auth.py 有钉），家属档案即使被误勾
        # is_staff 也照样拒。
        from family.models import is_family_user

        if is_family_user(user):
            return None
        return f"session:{user.pk}"

    return None  # ninja 收到 None → 401 Unauthorized
