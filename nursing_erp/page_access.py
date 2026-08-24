"""轻量页访问控制 — @login_required 收紧为 @staff_required（2026-08-24 家属端安全闭合）。

背景：轻量页原先只查"登录与否"，家属账号（User is_staff=False + FamilyMember 档案）
一旦登录即可看 /billing/ /kitchen/ 等全院看板。收紧后：
- 匿名 → /admin/login/?next=…（与原 @login_required 行为一致，既有测试不动）
- 员工（有 Employee 档案或 is_staff/is_superuser）且非家属 → 放行
- 家属 / 无员工档案的裸账号 → 302 /family/（家属端首页）
"""

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

FAMILY_HOME_URL = "/family/"


def _has_employee(user) -> bool:
    try:
        return user.employee is not None
    except Exception:
        return False


def staff_required(view_func):
    """轻量页员工门 — 家属与裸账号弹回家属端。"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        from family.models import is_family_user

        if (user.is_staff or user.is_superuser or _has_employee(user)) and not is_family_user(user):
            return view_func(request, *args, **kwargs)
        return redirect(FAMILY_HOME_URL)

    return wrapper
