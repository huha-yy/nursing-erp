"""项目自有模板 filter — UNFOLD 侧栏嵌套导航配套。

坑：Django 模板里对无 "items" key 的 dict 取 item.items，会回退成
dict.items() 调用（返回 dict_items 视图，真值恒真）——不能拿
{% if item.items %} 判"有无子项"，必须经 is_nav_children 判型；
nav_deep_active 同样只认 dict 节点，解析假象一律当无子项。
"""

from django import template

register = template.Library()


@register.filter
def is_nav_children(items):
    """是否为真实的三级目录子项列表（dict 组成的非空可迭代）。"""
    try:
        lst = list(items or [])
    except TypeError:
        return False
    return bool(lst) and all(isinstance(n, dict) for n in lst)


@register.filter
def nav_deep_active(items):
    """UNFOLD has_nav_item_active 的递归版。

    原版（unfold/templatetags/unfold.py）只看一层 item["active"]，嵌套子项
    激活时组不会自动展开；本 filter 深度遍历 items 树。
    """

    def walk(nodes):
        for node in nodes or []:
            if not isinstance(node, dict):
                continue  # dict_items 视图等解析假象，非嵌套子项
            if node.get("active"):
                return True
            if node.get("items") and walk(node["items"]):
                return True
        return False

    return walk(items)
