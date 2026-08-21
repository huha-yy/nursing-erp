"""/api/ 认证回归测试（2026-08-21 P0 安全加固）。

覆盖 nursing_erp/api_auth.py 的三条路径：
1. X-API-Key 正确 → 放行
2. 无 key / 错 key → 401
3. 已登录 session → 放行（轻量页 JS 的路径）
以及轻量页的 @login_required 跳转。
"""

from django.test import Client


def _set_key(settings):
    settings.ERP_API_KEY = "test-api-key"


def test_anonymous_api_rejected(db, settings):
    """匿名请求 /api/ 必须 401（公网暴露场景的核心防线）"""
    _set_key(settings)
    assert Client().get("/api/residents/").status_code == 401


def test_wrong_key_rejected(db, settings):
    _set_key(settings)
    assert Client(HTTP_X_API_KEY="wrong-key").get("/api/residents/").status_code == 401


def test_missing_key_config_fails_closed(db, settings):
    """ERP_API_KEY 未配置时，密钥路径永不放行（fail-closed，不退化为无认证）"""
    settings.ERP_API_KEY = ""
    c = Client(HTTP_X_API_KEY="")
    assert c.get("/api/residents/").status_code == 401


def test_valid_key_accepted(client, db):
    resp = client.get("/api/residents/")  # conftest 的 client 自带正确 key
    assert resp.status_code == 200


def test_logged_in_session_accepted(db, settings, django_user_model):
    """轻量页登录后，fetch 同源带 cookie 即可访问（无需 API key）"""
    _set_key(settings)
    django_user_model.objects.create_user(username="caregiver1", password="pw123456")
    c = Client()
    assert c.login(username="caregiver1", password="pw123456")
    assert c.get("/api/residents/").status_code == 200


def test_light_page_redirects_to_admin_login(db):
    """未登录访问 /kitchen/ → 跳转 admin 登录页并带 next 回跳参数"""
    resp = Client().get("/kitchen/")
    assert resp.status_code == 302
    assert resp["Location"].startswith("/admin/login/")
    assert "next=/kitchen/" in resp["Location"]
