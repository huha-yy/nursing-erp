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
