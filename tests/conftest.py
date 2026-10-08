import os
import django

import pytest
from django.test import Client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nursing_erp.settings")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")

django.setup()


@pytest.fixture(autouse=True)
def _isolate_demo_lang_marker(monkeypatch):
    """测试与生产 demo_lang marker 隔离。

    DemoLangDefaultMiddleware 读 DEMO_LANG_FILE（默认指向 ai 仓
    logs/demo_lang）：英文演示态时 marker=en，无 cookie 的测试请求会被
    强制激活 en，连锁打破 zh 断言（2026-10-08 踩过：marker=en 期间
    test_i18n_pages zh 用例 7 连挂）。测试一律视 marker 不存在。
    """
    monkeypatch.setenv("DEMO_LANG_FILE", "/nonexistent-demo-lang-marker")


@pytest.fixture(autouse=True)
def _reset_translation():
    """每用例后清掉线程级激活语言。

    set_language 视图 / LocaleMiddleware / translation.activate() 都会把
    "en" 等语言留在当前线程，连锁打破后续用例的中文断言（models 侧栏
    双语化后 get_*_display 也会走翻译，泄漏面变大，必须统一兜底）。
    """
    yield
    from django.utils import translation

    translation.deactivate()


@pytest.fixture
def client(db, settings):
    """/api/ 认证加固（2026-08-21）后的默认测试客户端：带 X-API-Key 头。

    页面类测试不受影响（页面不校验此头）。需要测匿名/未授权行为时，
    直接用 django.test.Client() 构造（见 test_api_auth.py）。
    """
    settings.ERP_API_KEY = "test-api-key"
    return Client(HTTP_X_API_KEY="test-api-key")
