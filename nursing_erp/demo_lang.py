# nursing_erp/demo_lang.py
"""演示态语言缺省中间件（2026-10-08，配合 ai-nursing-home switch_demo_lang.sh）。

链路：ai-nursing-home/scripts/switch_demo_lang.sh 切换中/英文演示数据时写
标记文件 logs/demo_lang（keepfresh cron 同源）。本中间件让 UI 语言缺省值
跟随该标记——浏览器未显式点过右上角语言切换（无语言 cookie）时：标记 en →
激活英文；标记 zh / 缺失 / 非法 → 不干预（走 LANGUAGE_CODE=zh-hans 既有
缺省）。显式 cookie 永远优先，个人临时切换不受影响。放在 LocaleMiddleware
之后（覆盖其按 Accept-Language/LANGUAGE_CODE 做出的缺省选择）。
"""

from __future__ import annotations

import os

from django.conf import settings
from django.utils import translation

_MARKER_PATH = os.environ.get(
    "DEMO_LANG_FILE",
    "/home/nursing-home/huha-project/ai-nursing-home/logs/demo_lang",
)


def _marker_lang() -> str | None:
    try:
        with open(_MARKER_PATH, encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return None
    return v if v in ("en", "zh") else None


class DemoLangDefaultMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        marker = _marker_lang()
        # Django 5.2 Settings 无 LANGUAGE_COOKIE 属性（set_language 实际写
        # django_language，见 urls.py 语言切换端点注释）
        cookie_name = getattr(settings, "LANGUAGE_COOKIE", "django_language")
        has_cookie = bool(request.COOKIES.get(cookie_name))
        if marker == "en" and not has_cookie:
            translation.activate("en")
            request.LANGUAGE_CODE = translation.get_language()
        return self.get_response(request)
