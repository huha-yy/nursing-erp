"""i18n 基础设施钉子（广交会双语化 P1）。

钉三件事：
1. zh-hans（默认语言）下运行时改名的内置模型/应用显示中文——保既有中文断言口径；
2. en 激活下同一批显示英文 msgid——切换真的生效；
3. /i18n/setlang/ POST 切语言写 django_language cookie 并回跳。

注意：用例内 translation.activate() 必须在 finally 里 deactivate，
防语言泄漏连锁打破其他用例的中文断言（见 conftest 说明）。
"""
import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.test import Client
from django.utils import translation

# urls.py 的运行时改名在模块导入时执行——测试进程里先强制导入
import nursing_erp.urls  # noqa: F401, E402

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "getter",
    [
        # urls.py 运行时改名的内置对象（gettext_lazy 包裹）
        lambda: apps.get_app_config("auth").verbose_name,
        lambda: User._meta.verbose_name,
    ],
    ids=["auth-app-verbose-name", "user-verbose-name"],
)
def test_builtin_names_follow_language(getter):
    translation.activate("zh-hans")
    try:
        assert str(getter()) == "系统管理" or str(getter()) == "用户账号"
    finally:
        translation.deactivate()
    translation.activate("en")
    try:
        assert str(getter()) in ("System Management", "User Accounts")
    finally:
        translation.deactivate()


def test_index_page_switches_language(client):
    """admin 首页标题随语言切换（SITE_HEADER 走模板翻译后此处应加强）。"""
    User.objects.create_superuser("i18n_admin", "a@a.com", "pw")
    admin_client = Client()
    admin_client.force_login(User.objects.get(username="i18n_admin"))

    # 默认 zh-hans：无 cookie/头 → LANGUAGE_CODE
    resp = admin_client.get("/admin/")
    assert resp.status_code == 200
    assert "System Management".encode() not in resp.content  # 未切 en 前不露英文

    # en cookie → 英文渲染
    resp = admin_client.get("/admin/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 200
    assert b"System Management" in resp.content


def test_set_language_view_writes_cookie():
    c = Client()
    resp = c.post("/i18n/setlang/", {"language": "en", "next": "/admin/"})
    assert resp.status_code == 302
    assert resp["Location"] == "/admin/"
    assert c.cookies["django_language"].value == "en"

    # 切回 zh
    resp = c.post("/i18n/setlang/", {"language": "zh-hans", "next": "/admin/"})
    assert c.cookies["django_language"].value == "zh-hans"
