"""项目自有模板 filter — UNFOLD 侧栏嵌套导航配套。"""

from django import template

register = template.Library()


@register.filter
def nav_deep_active(items):
    """UNFOLD has_nav_item_active 的递归版。

    原版（unfold/templatetags/unfold.py）只看一层 item["active"]，嵌套子项
    激活时组不会自动展开；本 filter 深度遍历 items 树。
    """

    def walk(nodes):
        for node in nodes or []:
            if node.get("active"):
                return True
            if node.get("items") and walk(node["items"]):
                return True
        return False

    return walk(items)
