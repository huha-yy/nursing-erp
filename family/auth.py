"""家属 API 认证 — 镜像 nursing_erp/api_auth.py 的 fail-closed 风格。

/api/family/ 挂在独立的 NinjaAPI 实例上（不经 erp_auth，两种身份互不串门）：
1. 机器路径（dl-control 的家属对话预取）：X-API-Key（服务间）+ X-Family-Token
   （哪位家属——/auth/ 登录端点换取，泄漏可经 admin「重新生成令牌」作废）
2. 页面路径（家属页 JS）：家属登录 session，同源 fetch 自动带 cookie

任一路径都要求 FamilyMember 档案且 is_active——员工 session 在此天然 401，
家属 session 同样进不了员工 /api/（api_auth.erp_auth 按档案拒绝）。
"""

import secrets

from django.conf import settings

from .models import FamilyMember


def api_key_auth(request):
    """仅验服务间 X-API-Key — POST /auth/ 登录端点专用（此时还没有 family token）。"""
    expected = getattr(settings, "ERP_API_KEY", "")
    provided = request.headers.get("X-API-Key", "")
    if expected and provided and secrets.compare_digest(provided, expected):
        return "api-key"
    return None


def family_auth(request):
    """家属身份解析 — 返回 FamilyMember 实例（落 request.auth），未识别返回 None→401。"""
    if api_key_auth(request) is not None:
        token = request.headers.get("X-Family-Token", "").strip()
        if not token:
            return None  # key 有效但没带家属令牌：fail-closed，不退化为"全体家属"
        return FamilyMember.objects.filter(token=token, is_active=True).first()
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return FamilyMember.objects.filter(user=user, is_active=True).first()
    return None
