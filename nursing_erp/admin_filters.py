"""Admin 筛选器数据值显示层翻译（广交会英文演示收口）。

背景：OperationLog.action（自由文本，record() 埋点 + 中间件路径表写入）
和 auth Group.name（种子数据行）落库恒中文——AI 查询词表/演示数据依赖
中文值。en 下 admin 筛选下拉显示的是 DB 原值，模板侧无法插手，只能
在 ListFilter.choices() 里经 gettext 翻译。

只翻译 isinstance(display, str) 的条目：Django 自产的 "All" 是 lazy
proxy（已按请求语言解析），再过一遍 gettext 会把 zh 的「全部」当 msgid
查不到而卡死中文——跳过。
"""

from django.contrib.admin.filters import AllValuesFieldListFilter, RelatedFieldListFilter
from django.utils.translation import gettext


class TranslatedAllValuesFieldListFilter(AllValuesFieldListFilter):
    """DB distinct 值筛选（如 OperationLog.action）显示层翻译。"""

    def choices(self, changelist):
        for c in super().choices(changelist):
            if isinstance(c.get("display"), str):
                c["display"] = gettext(c["display"])
            yield c


class TranslatedRelatedFieldListFilter(RelatedFieldListFilter):
    """外键对象名筛选（如 User.groups）显示层翻译。"""

    def choices(self, changelist):
        for c in super().choices(changelist):
            if isinstance(c.get("display"), str):
                c["display"] = gettext(c["display"])
            yield c
