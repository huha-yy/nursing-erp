"""家属端页面 — 薄视图（fat-JS 页面范式，数据全部来自 /api/family/*）。

与员工轻量页的差别：
- 门是 family_required（家属身份）而非 staff_required——员工访问家属页弹回登录页
- 登录页独立（/family/login/，手机号+密码），不复用 admin 登录（家属非 staff，
  走 admin 登录页既报"凭据错误"又暴露员工入口）
"""

from functools import wraps

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import FamilyMember

FAMILY_LOGIN_URL = "/family/login/"


def _member(request) -> FamilyMember | None:
    user = request.user
    if not user.is_authenticated:
        return None
    return FamilyMember.objects.filter(user=user, is_active=True).first()


def family_required(view_func):
    """家属页门：匿名/非家属 → /family/login/?next=…（员工无档案，同样进不来）。"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _member(request) is None:
            return redirect_to_login(request.get_full_path(), FAMILY_LOGIN_URL)
        return view_func(request, *args, **kwargs)

    return wrapper


@require_http_methods(["GET", "POST"])
def family_login(request):
    """家属登录 — 手机号即 User.username；非家属账号明确报错（不进员工体系）。"""
    error = ""
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("phone", "").strip(),
            password=request.POST.get("password", ""),
        )
        member = None
        if user is not None:
            member = FamilyMember.objects.filter(user=user, is_active=True).first()
        if member is None:
            error = "手机号或密码错误，或该账号不是家属账号"
        else:
            login(request, user)
            nxt = request.POST.get("next") or request.GET.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") else "/family/")
    return render(request, "family_login.html", {"error": error})


def family_logout(request):
    logout(request)
    return redirect(FAMILY_LOGIN_URL)


@family_required
def family_home(request):
    return render(request, "family_home.html")


@family_required
def family_care(request, resident_id: int | None = None):
    return render(request, "family_care.html", {"resident_id": resident_id})


@family_required
def family_order(request):
    return render(request, "family_order.html")


@family_required
def family_billing(request):
    return render(request, "family_billing.html")


@family_required
def family_password(request):
    """改密码 — update_session_auth_hash 防改完即掉线。"""
    member = _member(request)
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            return redirect("/family/password/?changed=1")
        error = form.errors.get("__all__", ["请检查填写项"])[0]
        ctx = {"form": form, "error": error, "member": member}
        return render(request, "family_password.html", ctx)
    form = PasswordChangeForm(request.user)
    return render(request, "family_password.html", {"form": form, "member": member})
